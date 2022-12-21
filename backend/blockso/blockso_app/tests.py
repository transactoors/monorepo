# std lib imports
from datetime import datetime, timedelta, timezone
from unittest import mock
import json
import pytz

# third party imports
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from rest_framework.test import APITestCase
from siwe_auth.models import Nonce
from siwe.siwe import SiweMessage
import eth_account
import fakeredis
import responses
import rq

# our imports
from .models import Follow, Post, Profile, Transaction, \
                    ERC20Transfer, ERC721Transfer
from . import jobs


UserModel = get_user_model()


class BaseTest(APITestCase):
    """ Base class for all tests. """

    @classmethod
    def setUpClass(cls):
        """ Runs once before all tests. """

        super(BaseTest, cls).setUpClass()
        cls.maxDiff = None  # more verbose test output

        # create a test wallet (signer)
        cls.test_signer = eth_account.Account.create()
        cls.test_signer_2 = eth_account.Account.create()

        # sample tx history json for erc20 transactions
        next_update = datetime.now(timezone.utc) + timedelta(minutes=5)
        next_update = next_update.isoformat().replace("+00:00", "000Z")
        cls.covalent_next_update = next_update
        with open(
            "./blockso_app/covalent-tx-history-sample.json",
            "r",
            encoding="utf-8"
        ) as fobj:
            content = fobj.read() 
            # replace all occurrences of the address in the tx history sample
            # with the address of our test signer
            content = content.replace(
                "0xa79e63e78eec28741e711f89a672a4c40876ebf3",
                cls.test_signer.address.lower()
            )

            # replace the next_update_at field with a time 5 min in the future
            content = content.replace(
                "REPLACEME_NEXT_UPDATE_AT",
                cls.covalent_next_update
            )
            cls.erc20_tx_resp_data = content

        # sample tx history json for erc721 transactions
        with open(
            "./blockso_app/covalent-tx-history-erc721.json",
            "r",
            encoding="utf-8"
        ) as fobj:
            content = fobj.read() 
            # replace all occurrences of the address in the tx sample
            # with the address of our test signer
            content = content.replace(
                "0xc9eb983357b88921a89844d7047589a37b563108",
                cls.test_signer.address.lower()
            )

            # replace the next_update_at field with a time 5 min in the future
            content = content.replace(
                "REPLACEME_NEXT_UPDATE_AT",
                cls.covalent_next_update
            )
            cls.erc721_tx_resp_data = content

    def setUp(self):
        """ Runs before each test. """

        super().setUp()

        # mock redis backend for use in tests 
        self.redis_backend = fakeredis.FakeRedis()
        redis_patcher = mock.patch(
            "redis.from_url",
            return_value=self.redis_backend
        )
        redis_patcher.start()

        # create redis queue and scheduled jobs registry for use in tests
        self.redis_queue = rq.Queue(
            connection=self.redis_backend,
            is_async=False
        )
        self.scheduled_job_registry = rq.registry.ScheduledJobRegistry(
            queue=self.redis_queue
        )

        # fake requests/responses
        self.mock_responses = responses.RequestsMock()
        self.mock_responses.start()

        # clean up all mock patches in the end
        self.addCleanup(mock.patch.stopall)

        # common data for updating profile
        self.update_profile_data = {
            "image": "https://ipfs.io/ipfs/QmRRPWG96cmgTn2qSzjwr2qvfNEuhunv6FNeMFGa9bx6mQ",
            "bio": "Hello world, I am a user.",
            "socials": {
                "website": "https://mysite.com/",
                "telegram": "https://t.me/nullbitx8",
                "discord": "https://discord.gg/nullbitx8",
                "twitter": "https://twitter.com/nullbitx8",
                "opensea": "https://opensea.com/nullbitx8.eth",
                "looksrare": "https://looksrare.org/nullbitx8.eth",
                "snapshot": "https://snapshot.org/nullbitx8.eth"
            }
        }

        # common data for creating posts
        self.create_post_data = { 
            "text": "",
            "tagged_users": [],
            "imgUrl": "",
            "isShare": False,
            "isQuote": False,
            "refPost": None,
            "refTx": None
        }

    def tearDown(self):
        """ Runs after each test. """

        super().tearDown()

        # clean up fake redis backend
        self.redis_backend.flushall()

        # clean up fake requests/responses
        self.mock_responses.stop()
        self.mock_responses.reset()

    def _get_siwe_message_data(self, signer):
        """ Returns common data used for siwe (sign in with ethereum). """

        return {
            "address": signer.address,
            "domain": "127.0.0.1",
            "version": "1",
            "chain_id": "1",
            "uri": "http://127.0.0.1/api/auth/login",
            "nonce": "",
            "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }

    def _do_login(self, signer):
        """
        Utility function to get a nonce, sign a message, and do a login.
        Returns the response of the login request.
        Note: the authentication backend creates a user if one
        does not already exist for the wallet doing the authentication.
        """
        # get nonce from backend
        resp = self.client.get("/api/auth/nonce/")
        nonce = resp.data["nonce"]

        # prepare message
        message_data = self._get_siwe_message_data(signer)
        message_data["nonce"] = nonce
        message = SiweMessage(message_data).sign_message()

        # sign message
        signed_msg = signer.sign_message(
            eth_account.messages.encode_defunct(text=message)
        )

        # make login request
        url = "/api/auth/login/"
        data = {
            "message": message,
            "signature": signed_msg.signature.hex()
        }
        resp = self.client.post(url, data)

        # return response
        return resp

    def _do_logout(self):
        """
        Utility function to log out a user.
        Returns the response of the logout request.
        """
        url = "/api/auth/logout/"
        return self.client.post(url)

    def _create_users(self, amount):
        """
        Utility function to create amount number of users.
        Returns a list of signers that contain the wallets
        of all the created users.
        """
        signers = []
        for i in range(amount):
            signer = eth_account.Account.create()
            self._do_login(signer)  # a user is created when signer logs in
            signers.append(signer)

        return signers

    def _update_profile(self, signer):
        """
        Utility function to create a Profile using
        the given test data.
        This function will usually be called after authenticating
        with the _do_login function above.
        """
        # update profile
        url = f"/api/{signer.address}/profile/"
        resp = self.client.put(url, self.update_profile_data)
        return resp

    def _create_post(self, tagged_users=[]):
        """
        Utility function to create a post.
        Returns the response of creating a post.
        """
        # prepare request
        url = f"/api/post/"
        data = self.create_post_data
        data["text"] = "My first post!"
        data["imgUrl"] = "https://fakeimage.com/img.png"
        data["tagged_users"] = tagged_users

        # send request
        resp = self.client.post(url, data)

        return resp

    def _repost(self, post_id):
        """
        Utility function to repost a post.
        Returns the response of creating the repost.
        """
        # prepare request
        url = f"/api/post/"
        data = self.create_post_data
        data["isShare"] = True
        data["refPost"] = post_id

        # send request
        resp = self.client.post(url, data)

        return resp

    def _create_comment(self, post_id, text, tagged_users=[]):
        """
        Utility function to create a comment on a post.
        Returns the response of creating a comment.
        """
        url = f"/api/posts/{post_id}/comments/"
        data = {"text": text, "tagged_users": tagged_users}
        resp = self.client.post(url, data)
        return resp

    def _follow_user(self, address):
        """
        Utility function to follow the user with the given address.
        Returns the response of following the user.
        """
        url = f"/api/{address}/follow/"
        resp = self.client.post(url)
        return resp


class AuthTests(BaseTest):
    """
    Tests authentication using ETH wallet.
    Auth is based on https://eips.ethereum.org/EIPS/eip-4361
    and https://github.com/payton/django-siwe-auth/blob/main/siwe_auth/views.py
    """

    def test_nonce(self):
        """
        Assert that a nonce is returned to the user.
        """
        # set up test
        url = "/api/auth/nonce/"

        # make request
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        nonce = Nonce.objects.all()[0]
        self.assertEqual(resp.data["nonce"], nonce.value) 

    def test_login(self):
        """
        Assert that a user can create a session by signing a message.
        """
        # do login
        resp = self._do_login(self.test_signer)

        # make assertions
        # assert that the user has a session
        self.assertEqual(resp.status_code, 200)
        session_key = self.client.cookies.get("sessionid").value
        session = Session.objects.get(session_key=session_key)
        session_data = session.get_decoded()
        self.assertEqual(
            session_data["_auth_user_id"],
            self.test_signer.address
        )

    def test_logout(self):
        """
        Assert that a user can terminate their session by logging out.
        """
        # prepare test
        self._do_login(self.test_signer)

        # logout
        resp = self.client.post("/api/auth/logout/")

        # make assertions
        # assert that the user no longer has a session
        self.assertEqual(resp.status_code, 200)
        session_key = self.client.cookies.get("sessionid").value
        self.assertEqual(session_key, "")

    def test_logout_unauthed(self):
        """
        Assert that a user can call logout even if they are not authenticated.
        """
        # prepare test
        # logout
        resp = self.client.post("/api/auth/logout/")

        # make assertions
        # assert that the user no longer has a session
        self.assertEqual(resp.status_code, 200)


class ProfileTests(BaseTest):
    """ Tests profile related behavior. """

    def test_create_profile(self):
        """
        Assert that a profile is created when a user signs in for the first time.
        Assert that the created profile info is returned as JSON.
        """
        # prepare test and create profile
        self._do_login(self.test_signer)
        
        # make assertions
        url = f"/api/{self.test_signer.address}/profile/"
        resp = self.client.get(url)
        self.assertEqual(resp.data["address"], self.test_signer.address)
        self.assertEqual(resp.data["image"], "")
        self.assertEqual(resp.data["bio"], "")

    def test_update_profile(self):
        """
        Assert that a profile is updated successfully.
        Assert that the updated profile info is returned as JSON.
        """
        # prepare test
        self._do_login(self.test_signer)

        # change some profile info
        update_data = self.update_profile_data
        update_data["image"] = "https://ipfs.io/ipfs/nonexistent"
        update_data["bio"] = "short bio"
        update_data["socials"]["website"] = "https://newsite.com"

        # make PUT request
        url = f"/api/{self.test_signer.address}/profile/"
        resp = self.client.put(url, update_data)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        expected = update_data
        expected.update({
            "address": self.test_signer.address,
            "numFollowers": 0,
            "numFollowing": 0,
            "followedByMe": False
        })
        self.assertDictEqual(resp.data, expected)

    # TODO remove or update this patch when a job queue is added
    @mock.patch("blockso_app.jobs.process_address_txs", lambda x: None)
    def test_retrieve_profile(self):
        """
        Assert that a profile is retrieved successfully.
        """
        # prepare test
        self._do_login(self.test_signer)
        self._update_profile(self.test_signer)

        # make GET request
        url = f"/api/{self.test_signer.address}/profile/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        expected = self.update_profile_data
        expected.update({
            "address": self.test_signer.address,
            "numFollowers": 0,
            "numFollowing": 0,
            "followedByMe": False
        })
        self.assertDictEqual(resp.data, expected)

    def test_retrieve_user(self):
        """
        Assert that a user can get their own info once logged in.
        """
        # prepare test
        self._do_login(self.test_signer)

        # make request
        resp = self.client.get("/api/user/")

        # make assertions
        # assert that the user receives information about themselves
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.data["address"],
            self.test_signer.address
        )
        self.assertIsNotNone(resp.data["profile"])

    def test_retrieve_user_unauthed(self):
        """
        Assert that a user cannot get their own info
        if they are not logged in.
        """
        # prepare test
        # make request
        resp = self.client.get("/api/user/")
        
        # assert 403
        self.assertEqual(resp.status_code, 403)

    def test_get_suggested_users(self):
        """
        Assert that users starting with the given
        query are returned successfully.
        """
        # prepare test
        self._do_login(self.test_signer)
        self._do_logout()
        self._do_login(self.test_signer_2)

        # make request
        # query using 0x + the first 3 characters of the address
        query = self.test_signer.address[:5]
        resp = self.client.get(f"/api/users/?q={query}")
        
        # assert 200
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["address"], self.test_signer.address)

    def test_get_suggested_users_too_short(self):
        """
        Assert that a 400 is returned when the
        query for the users is less than the required length.
        """
        # prepare test
        self._do_login(self.test_signer)
        self._do_logout()
        self._do_login(self.test_signer_2)

        # make request
        # query using an empty string
        query = ""
        resp = self.client.get(f"/api/users/?q={query}")
        
        # assert 400
        self.assertEqual(resp.status_code, 400)


class FollowTests(BaseTest):
    """
    Tests follow related behavior.
    """

    def test_follow(self):
        """
        Assert that a user can follow another.
        """
        # prepare test
        # create user 1
        self._do_login(self.test_signer)
        self._do_logout()

        # create user 2
        self._do_login(self.test_signer_2)
        self._do_logout()

        # make request for user 1 to follow user 2
        self._do_login(self.test_signer)
        url = f"/api/{self.test_signer_2.address}/follow/"
        resp = self.client.post(url)

        # make assertions
        self.assertEqual(resp.status_code, 201)
        follow = Follow.objects.get(
            src_id=Profile.objects.get(user_id=self.test_signer.address),
            dest_id=Profile.objects.get(user_id=self.test_signer_2.address)
        )
        self.assertIsNotNone(follow)

    def test_unfollow(self):
        """
        Assert that a user can unfollow another.
        """
        # prepare test
        # create user 1 and log them in
        self._do_login(self.test_signer)

        # create user 2
        url = f"/api/{self.test_signer_2.address}/profile/"
        self.client.post(url, self.update_profile_data)

        # make request for user 1 to follow user 2
        url = f"/api/{self.test_signer_2.address}/follow/"
        resp = self.client.post(url)

        # make request for user 1 to UNFOLLOW user 2
        url = f"/api/{self.test_signer_2.address}/follow/"
        resp = self.client.delete(url)

        # make assertions
        self.assertEqual(resp.status_code, 204)
        with self.assertRaises(Follow.DoesNotExist):
            Follow.objects.get(
                src=Profile.objects.get(user_id=self.test_signer.address),
                dest=Profile.objects.get(user_id=self.test_signer_2.address)
            )

    def test_get_followers_following(self):
        """
        Assert that a user can see who follows a user.
        Assert that a user can see who a user follows.
        """
        # prepare test
        # create users 1 and 2
        # and make user 2 follow user 1
        self._do_login(self.test_signer)
        self._do_logout()
        self._do_login(self.test_signer_2)
        self._follow_user(self.test_signer.address)

        # make request to get followers of user 1
        url = f"/api/{self.test_signer.address}/followers/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(
            resp.data["results"][0]["address"],
            self.test_signer_2.address
        )
        self.assertIsNone(resp.data["next"])

        # make request to get following of user 2
        url = f"/api/{self.test_signer_2.address}/following/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(
            resp.data["results"][0]["address"],
            self.test_signer.address
        )
        self.assertIsNone(resp.data["next"])

    def test_get_followers_ordering(self):
        """
        Assert that the followers of a user are
        ordered based on when they were followed,
        from most recent to least recent.
        """
        # prepare test
        # create 5 users and make them follow user 1
        signers = self._create_users(5)
        for i in range(1, len(signers)):
            self._do_login(signers[i])
            self._follow_user(signers[0].address)

        # get the followers of user 1
        url = f"/api/{signers[0].address}/followers/"
        resp = self.client.get(url)

        # assert that the followers are ordered by most recent
        followers = resp.data["results"]
        for i in range(len(followers)):
            self.assertEqual(
                followers[i]["address"],
                signers[4-i].address
            )

    def test_get_following_ordering(self):
        """
        Assert that the following of a user
        are ordered based on when they were followed
        by the user, from most recent to least recent.
        """
        # prepare test
        # create 5 users and make user 1 follow them all
        signers = self._create_users(5)
        self._do_login(signers[0])
        for i in range(1, len(signers)):
            self._follow_user(signers[i].address)

        # get the following of user 1
        url = f"/api/{signers[0].address}/following/"
        resp = self.client.get(url)

        # assert that the following are ordered by most recent
        following = resp.data["results"]
        for i in range(len(following)):
            self.assertEqual(
                following[i]["address"],
                signers[4-i].address
            )


class TransactionParsingTests(BaseTest):
    """
    Tests behavior related to getting transaction history
    and using it to create Posts.
    """

    def _mock_tx_history_response(self, address, json_response):
        """
        Mocks a response for user tx history.
        """
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(address, 0),
            body=json_response
        )

    def test_process_address_txs(self):
        """
        Assert that an address' tx history is retrieved
        and parsed correctly.
        Assert that the address now has Transactions that
        reflect their transaction history.
        """
        # set up test
        self._mock_tx_history_response(
            self.test_signer.address,
            self.erc20_tx_resp_data
        )

        # call function
        jobs.process_address_txs(self.test_signer.address)

        # make assertions
        # assert that the correct number of Transactions has been created
        tx_count = Transaction.objects.all().count()
        self.assertEqual(tx_count, 6)

    def test_process_erc20_transfers(self):
        """
        Assert that an address' tx history is retrieved
        and parsed correctly.
        Assert that the address now has ERC20Transfers that
        reflect their transaction history.
        """
        # set up test
        self._mock_tx_history_response(self.test_signer.address, self.erc20_tx_resp_data)

        # call function
        jobs.process_address_txs(self.test_signer.address)

        # make assertions
        # assert that the correct number of ERC20Transfers has been created
        transfer_count = ERC20Transfer.objects.all().count()
        self.assertEqual(transfer_count, 2)

    def test_process_erc721_transfers(self):
        """
        Assert that a user's history with erc721 txs
        is parsed and stored correctly.
        """
        # set up test
        self._mock_tx_history_response(
            self.test_signer.address,
            self.erc721_tx_resp_data
        )

        # call function
        jobs.process_address_txs(self.test_signer.address)

        # make assertions
        # assert that the correct number of Transactions has been created
        tx_count = Transaction.objects.all().count()
        self.assertEqual(tx_count, 1)

        # assert that the correct number of Posts has been created
        # there should be as many Posts as Transactions/Transfers where
        # the post author is the from address
        self.assertEqual(Post.objects.all().count(), 1)

        # assert that the correct number of ERC721Transfers has been created
        erc721_transfer_count = ERC721Transfer.objects.all().count()
        self.assertEqual(erc721_transfer_count, 1)

    def test_posts_originate_from_address(self):
        """
        Assert that posts are only created for
        transactions or transfers that originate
        from the given address.
        This is meant to reduce spam and provide more
        quality posts.
        """
        # set up test
        self._mock_tx_history_response(self.test_signer.address, self.erc20_tx_resp_data)

        # call function
        jobs.process_address_txs(self.test_signer.address)

        # make assertions
        # assert that the correct number of Posts has been created
        post_count = Post.objects.all().count()
        self.assertEqual(post_count, 6)

    def test_process_address_tx_no_limit(self):
        """
        Assert that the entire tx history of a user is paginated
        through when the 'limit' argument is None and covalent
        says there are more pages with results.
        """
        # set up test
        # mock first covalent response to indicate there are more results
        has_more_results = self.erc20_tx_resp_data.replace(
            '"has_more": false',
            '"has_more": true'
        )
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(self.test_signer.address, 0),
            body=has_more_results
        )

        # mock second covalent response to indicate there are no more results
        # note that the url being mocked has page number 1 which means
        # we are expecting the code to paginate through the results
        no_more_results = self.erc721_tx_resp_data
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(self.test_signer.address, 1),
            body=no_more_results
        )

        # run the job
        jobs.process_address_txs(self.test_signer.address, limit=None)

        # assert that all of the users' tx history was parsed
        self.assertEqual(ERC721Transfer.objects.all().count(), 1)
        self.assertEqual(ERC20Transfer.objects.all().count(), 2)


class BackgroundJobTests(BaseTest):
    """
    Test the background job system.
    """

    def test_schedule_all_users_tx_history_job(self):
        """
        Assert that a job to fetch all users' tx histories
        is scheduled during the job that fetches one user's
        tx history.
        Assert that the job is scheduled to run on the
        'next_update_at' time given by covalent.
        """
        # set up test
        self._do_login(self.test_signer)
        # mock out the request for getting the user's tx history
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(self.test_signer.address, 0),
            body=self.erc20_tx_resp_data
        )

        # make request to process one user's tx history
        # which should trigger the scheduling of a job to
        # process all users' tx history
        jobs.process_address_txs(self.test_signer.address)

        # assert that a new job is scheduled to process all users' tx history
        self.assertTrue(
            jobs.scheduled_job_name in self.scheduled_job_registry
        )

    def test_schedule_all_users_tx_history_job_already_exists(self):
        """
        Assert that a second job isn't scheduled if one
        is already scheduled.
        """
        # set up test
        self._do_login(self.test_signer)
        # mock out the request for getting the user's tx history
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(self.test_signer.address, 0),
            body=self.erc20_tx_resp_data
        )
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(self.test_signer.address, 0),
            body=self.erc20_tx_resp_data
        )

        # make two requests to process one user's tx history
        # the first should schedule a job
        # the second should not schedule a job
        jobs.process_address_txs(self.test_signer.address)
        jobs.process_address_txs(self.test_signer.address)

        # assert that only one job is scheduled
        self.assertEqual(self.scheduled_job_registry.count, 1)

    def test_enqueue_all_users_tx_history(self):
        """
        Assert that the job creates a job for every user in the system.
        """
        # set up test
        # create users 1 and 2
        self._do_login(self.test_signer)
        self._do_login(self.test_signer_2)

        # run the job
        jobs.enqueue_all_users_tx_history(None)

        # assert that it added as many jobs as there are users
        # to the queue, where each job gets the tx history of that user
        self.assertEqual(
            self.redis_queue.count,
            UserModel.objects.all().count()
        )


class PostTests(BaseTest):
    """
    Test behavior around posts.
    """

    def test_create_post(self):
        """
        Assert that a post is created successfully by a logged in user.
        """
        # set up test
        self._do_login(self.test_signer)

        # make request
        resp = self._create_post()

        # make assertions
        self.assertEqual(resp.status_code, 201)

    def test_get_post(self):
        """
        Assert that a post is retrieved successfully by any user.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)

    @mock.patch("blockso_app.jobs.process_address_txs", mock.MagicMock)
    def test_get_posts(self):
        """
        Assert that a list of a user's posts are
        retrieved successfully by any user.
        Assert that the posts are paginated by 20.
        Assert that the posts are sorted in chronological
        order from most recent to least recent.
        """
        # set up test
        self._do_login(self.test_signer)

        # create 25 posts
        user = UserModel.objects.get(pk=self.test_signer.address)
        created_time = datetime.now(tz=pytz.UTC)
        for i in range(25):
            created_time = created_time + timedelta(hours=1)
            Post.objects.create(
                author=user.profile,
                created=created_time,
                isQuote=False,
                isShare=False
            )

        # make request
        url = f"/api/posts/{self.test_signer.address}/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        results = resp.data["results"]
        self.assertEqual(len(results), 20)  # 20 results

        # assert chronological ordering
        for i in range(1, len(results)):
            prev = i - 1
            self.assertGreaterEqual(
                datetime.fromisoformat(results[prev]["created"][:-1]),
                datetime.fromisoformat(results[i]["created"][:-1])
            )

    def test_update_post(self):
        """
        Assert that a post is updated successfully.
        Assert that the updated post is returned in the response.
        """
        # prepare test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        new_text = "My updated post."

        # change some post info
        update_data = self.create_post_data
        update_data["text"] = new_text 
        update_data["tagged_users"] = [self.test_signer.address]

        # make PUT request
        url = f"/api/post/{post_id}/"
        resp = self.client.put(url, update_data)

        # make assertions
        expected = resp.data
        expected["text"] = new_text
        self.assertEqual(resp.status_code, 200)
        self.assertDictEqual(resp.data, expected)

    def test_delete_post(self):
        """
        Assert that a post is deleted successfully.
        """
        # prepare test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # delete the post
        url = f"/api/post/{post_id}/"
        resp = self.client.delete(url)

        # make assertions
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(
            Post.objects.filter(
                author=Profile.objects.get(user_id=self.test_signer.address)
            ).count(),
            0
        )

    def test_get_post_ref_tx(self):
        """
        Assert that a post with a refTx will return
        the details of the transaction in the serialized
        post data response. 
        """
        # set up test
        self._do_login(self.test_signer)
        # create posts using the test covalent tx history API 
        self.mock_responses.add(
            responses.GET,
            jobs.get_tx_history_url(self.test_signer.address, 0),
            body=self.erc20_tx_resp_data
        )
        jobs.process_address_txs(self.test_signer.address)

        # assert that post 1 has a general reference transaction
        url = "/api/post/1/"
        resp = self.client.get(url)
        self.assertEqual(
            resp.data["refTx"]["tx_hash"],
            "0x3a6db035bb71e695628860d6f488b9f8deaa72ce506eace855"\
            "2a7c515346e323"
        )

        # assert that post 5 has a reference transaction
        # that includes erc20 transfers
        # refTx tied to them
        url = "/api/post/5/"
        resp = self.client.get(url)
        self.assertEqual(
            resp.data["refTx"]["tx_hash"],
            "0x9fd2eb7db94cf71ddc665b48dad42e1d00d90ace525fd6a047"\
            "9f958cce8a729f"
        )
        self.assertEqual(
            resp.data["refTx"]["erc20_transfers"][0]["contract_address"],
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        )

    def test_get_num_comments(self):
        """
        Assert that a post includes the
        number of comments on it.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        self._create_comment(post_id, text="hello")
        self._create_comment(post_id, text="world")

        # get the post details
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.data["numComments"], 2)

    def test_get_post_pfp(self):
        """
        Assert that a post includes the
        pfp of the author of the post.
        """
        # set up test
        self._do_login(self.test_signer)
        self._update_profile(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(
            resp.data["author"]["image"],
            self.update_profile_data["image"]
        )

    def test_tag_users_in_post(self):
        """
        Assert that a user can tag other users in a post.
        """
        # set up test
        self._do_login(self.test_signer)
        self._do_login(self.test_signer_2)

        # make request
        tagged = [self.test_signer.address]
        resp = self._create_post(
            tagged_users=tagged
        )

        # make assertions
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            resp.data["tagged_users"][0]["address"],
            tagged[0]
        )

    def test_like_unlike_post(self):
        """
        Assert that a user can like/unlike another user's post.
        """
        # set up test
        # user 1 creates post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request by user 2 to like user 1 post
        url = f"/api/post/{post_id}/likes/"
        self._do_login(self.test_signer_2)
        self.client.post(url)

        # assert post was liked successfully
        resp = self.client.get(url)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(
            resp.data["results"][0]["liker"]["address"], 
            self.test_signer_2.address
        )

        # make request by user 2 to unlike user 1 post
        resp = self.client.delete(url)

        # assert post was unliked successfully
        resp = self.client.get(url)
        self.assertEqual(resp.data["count"], 0)
        self.assertEqual(resp.data["results"], [])

    def test_like_post_twice(self):
        """
        Assert that a user cannot like a post twice.
        """
        # set up test
        # user 1 creates post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request by user 2 to like user 1's post twice
        url = f"/api/post/{post_id}/likes/"
        self._do_login(self.test_signer_2)
        self.client.post(url)
        resp = self.client.post(url)

        # assert second like was unsuccessful
        self.assertEqual(resp.status_code, 400)

        # assert that total likes is 1
        resp = self.client.get(url)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(
            resp.data["results"][0]["liker"]["address"], 
            self.test_signer_2.address
        )

    def test_get_post_num_likes(self):
        """
        Assert that the number of likes a post has is returned
        as part of the serialized Post data.
        """
        # set up test
        # user 1 creates post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # user 2 likes user 1's post
        url = f"/api/post/{post_id}/likes/"
        self._do_login(self.test_signer_2)
        self.client.post(url)

        # make request to get the post
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)
        
        # make assertions
        self.assertEqual(resp.data["numLikes"], 1)

    def test_get_post_liked_by_me(self):
        """
        Assert that likedByMe is True if the user liked the given post.
        Assert that likedByMe is False otherwise.
        """
        # set up test
        # user 1 creates post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # user 2 likes user 1's post
        url = f"/api/post/{post_id}/likes/"
        self._do_login(self.test_signer_2)
        self.client.post(url)

        # make request to get the post
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)
        
        # make assertions
        self.assertEqual(resp.data["likedByMe"], True)

    def test_repost(self):
        """
        Assert that a user can repost another user's post.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # repost as user 2
        self._do_login(self.test_signer_2)
        resp = self._repost(post_id)

        # assert that user 2 now has a post that references user 1's post
        self.assertEqual(resp.status_code, 201)
        new_post_id = resp.data["id"]
        url = f"/api/post/{new_post_id}/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["refPost"]["id"], post_id)
        self.assertEqual(
            resp.data["refPost"]["author"]["address"],
            self.test_signer.address
        )
        self.assertTrue(resp.data["isShare"])
        self.assertFalse(resp.data["isQuote"])
        self.assertIsNone(resp.data["refTx"])
        self.assertEqual(resp.data["text"], "")
        self.assertEqual(resp.data["imgUrl"], "")

    def test_resposted_by_me_and_num_reposts(self):
        """
        Assert that 'respostedByMe' is True if the user
        reposted the post in question.
        Assert that 'numReposts' is correct.
        """
        # prepare test
        # create post by user 1
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # repost as user 2
        self._do_login(self.test_signer_2)
        self._repost(post_id)

        # make request to get original post as user 2
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)
        
        # assert that repostedByMe is True
        self.assertTrue(resp.data["repostedByMe"])
        # assert that numReposts is equal to 1
        self.assertEqual(resp.data["numReposts"], 1)

        # get feed of user 2
        self._do_login(self.test_signer_2)
        url = f"/api/feed/"
        resp = self.client.get(url)

        # assert that repostedByMe is True
        self.assertEqual(resp.data["results"][0]["refPost"]["repostedByMe"], True)
        # assert that numReposts is equal to 1
        self.assertEqual(resp.data["results"][0]["refPost"]["numReposts"], 1)

    def test_get_reposted_by_me_unauthed(self):
        """
        Assert that 'respostedByMe' is False if the
        current user is not authenticated.
        """
        # prepare test
        # create post by user 1
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request to get original post as unauthed user
        self._do_logout()
        url = f"/api/post/{post_id}/"
        resp = self.client.get(url)
        
        # assert that repostedByMe is False
        self.assertFalse(resp.data["repostedByMe"])

    def test_cannot_repost_own_post(self):
        """
        Assert that a user cannot repost their own post.
        """
        # prepare test
        # create post by user 1
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # try to repost it as user 1
        resp = self._repost(post_id)

        # assert 400 BAD REQUEST
        self.assertEqual(resp.status_code, 400)

    def test_cannot_repost_item_twice(self):
        """
        Assert that a user cannot repost an item twice.
        """
        # prepare test
        # create post by user 1
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # repost it as user 2
        self._do_login(self.test_signer_2)
        self._repost(post_id)

        # try to repost it again and
        # assert 400 BAD REQUEST
        resp = self._repost(post_id)
        self.assertEqual(resp.status_code, 400)

    def test_cannot_repost_a_repost(self):
        """
        Assert that a user cannot repost a repost.
        """
        # prepare test
        # create post by user 1
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # repost it as user 2
        self._do_login(self.test_signer_2)
        resp = self._repost(post_id)
        repost_id = resp.data["id"]

        # repost the repost as user 1
        self._do_login(self.test_signer)
        resp = self._repost(repost_id)

        # assert 400 BAD REQUEST
        self.assertEqual(resp.status_code, 400)

    def test_delete_repost(self):
        """
        Assert that a user can delete their repost.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # repost as user 2
        self._do_login(self.test_signer_2)
        repost_id = self._repost(post_id)

        # make request to delete repost of original post_id
        url = f"/api/post/{post_id}/repost/"
        resp = self.client.delete(url)

        # assert deletion was successful
        self.assertEqual(resp.status_code, 204)
        url = f"/api/post/{repost_id}/" 
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)


class CommentsTests(BaseTest):
    """
    Test behavior around comments.
    """

    def test_create_comment(self):
        """
        Assert that a comment is created successfully by a logged in user.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request
        text = "I <3 your post!"
        resp = self._create_comment(post_id, text=text)

        # make assertions
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["id"], 1)
        self.assertEqual(resp.data["post"], 1)
        self.assertEqual(resp.data["text"], text)
        self.assertEqual(resp.data["tagged_users"], [])
        self.assertEqual(
            resp.data["author"]["address"],
            self.test_signer.address
        )

    def test_create_comment_empty(self):
        """
        Assert that creating an empty comment
        returns a 400 BAD REQUEST.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request
        resp = self._create_comment(post_id, text="")

        # make assertions
        self.assertEqual(resp.status_code, 400)

    def test_tag_users_in_comment(self):
        """
        Assert that a user can tag other users in a comment.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # make request
        text = f"I <3 @{self.test_signer.address}'s post!"
        tagged = [self.test_signer.address]
        resp = self._create_comment(
            post_id,
            text=text,
            tagged_users=tagged
        )

        # make assertions
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["text"], text)
        self.assertEqual(resp.data["tagged_users"][0]["address"], tagged[0])

    def test_list_comments(self):
        """
        Assert that a user can view comments on a post.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        self._create_comment(post_id, text="hello")

        # make request
        url = f"/api/posts/{post_id}/comments/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_list_comments_ordering(self):
        """
        Assert that comments are ordered from newest to oldest.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        self._create_comment(post_id, text="goodbye")
        self._create_comment(post_id, text="hello")

        # make request
        url = f"/api/posts/{post_id}/comments/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        results = resp.data["results"]
        self.assertEqual(results[0]["text"], "hello")
        self.assertEqual(results[1]["text"], "goodbye")

    def test_list_comments_pagination(self):
        """
        Assert that comments are paginated by 5.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # create 7 comments
        for i in range(7):
            self._create_comment(post_id, text=f"comment {i+1}")

        # make request
        url = f"/api/posts/{post_id}/comments/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 5)

        # make request for second page
        resp = self.client.get(resp.data["next"])

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 2)

    def test_list_comments_pfp(self):
        """
        Assert that a comment includes the pfp of its author
        as part of its deserialized data.
        """
        # set up test
        self._do_login(self.test_signer)
        self._update_profile(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        self._create_comment(post_id, text="hello")

        # make request
        url = f"/api/posts/{post_id}/comments/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(
            resp.data["results"][0]["author"]["image"],
            self.update_profile_data["image"]
        )

    def test_like_unlike_comment(self):
        """
        Assert that a user can like/unlike another user's comment.
        """
        # set up test
        # user 1 creates post and comment
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        resp = self._create_comment(post_id, "hello")
        comment_id = resp.data["id"]

        # make request by user 2 to like user 1's comment
        url = f"/api/posts/{post_id}/comments/{comment_id}/likes/"
        self._do_login(self.test_signer_2)
        self.client.post(url)

        # assert comment was liked successfully
        resp = self.client.get(url)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(
            resp.data["results"][0]["liker"]["address"], 
            self.test_signer_2.address
        )

        # make request by user 2 to unlike user 1 comment
        resp = self.client.delete(url)

        # assert comment was unliked successfully
        resp = self.client.get(url)
        self.assertEqual(resp.data["count"], 0)
        self.assertEqual(resp.data["results"], [])

    def test_like_comment_twice(self):
        """
        Assert that a user cannot like a comment twice.
        """
        # set up test
        # user 1 creates post and comment
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        resp = self._create_comment(post_id, "hello")
        comment_id = resp.data["id"]

        # make request by user 2 to like user 1's comment twice
        url = f"/api/posts/{post_id}/comments/{comment_id}/likes/"
        self._do_login(self.test_signer_2)
        resp = self.client.post(url)
        resp = self.client.post(url)

        # assert second like was unsuccessful
        self.assertEqual(resp.status_code, 400)

        # assert that total likes is 1
        resp = self.client.get(url)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(
            resp.data["results"][0]["liker"]["address"], 
            self.test_signer_2.address
        )

    def test_get_comment_num_likes(self):
        """
        Assert that the number of likes a comment has is returned
        as part of the serialized Comment data.
        """
        # set up test
        # user 1 creates post and comment
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        resp = self._create_comment(post_id, "hello")
        comment_id = resp.data["id"]

        # user 2 likes user 1's comment
        url = f"/api/posts/{post_id}/comments/{comment_id}/likes/"
        self._do_login(self.test_signer_2)
        self.client.post(url)

        # make request to get the comment
        url = f"/api/posts/{post_id}/comments/{comment_id}/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.data["numLikes"], 1)

    def test_get_comment_liked_by_me(self):
        """
        Assert that likedByMe is True if the user liked the given comment.
        Assert that likedByMe is False otherwise.
        """
        # set up test
        # user 1 creates post and comment
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        resp = self._create_comment(post_id, "hello")
        comment_id = resp.data["id"]

        # user 2 likes user 1's comment
        url = f"/api/posts/{post_id}/comments/{comment_id}/likes/"
        self._do_login(self.test_signer_2)
        resp = self.client.post(url)

        # make request to get the comment
        url = f"/api/posts/{post_id}/comments/{comment_id}/"
        resp = self.client.get(url)
        
        # make assertions
        self.assertEqual(resp.data["likedByMe"], True)


class FeedTests(BaseTest):
    """
    Test behavior around feeds.
    """

    def test_get_feed(self):
        """
        Assert that a logged in user can get a feed of posts.
        """
        # set up test
        self._do_login(self.test_signer)

        # make request to get a feed
        url = "/api/feed/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 0)

    def test_get_feed_does_not_follow_others(self):
        """
        Assert that if a user is not following anyone,
        only their own posts will show up in their feed.
        """
        # set up test
        self._do_login(self.test_signer)
        resp = self._create_post()
        expected_posts = [resp.data]

        # make request to get a feed
        url = "/api/feed/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"], expected_posts)

    def test_get_feed_follows_others(self):
        """
        Assert that if a user is following others,
        both their posts and those they follow will show up in their feed.
        """
        # set up test
        # login user 2, create a post
        self._do_login(self.test_signer_2)
        resp = self._create_post()

        # logout user 2
        self._do_logout()

        # login user 1, create a post, and follow user 2
        self._do_login(self.test_signer)
        resp = self._create_post()
        url = f"/api/{self.test_signer_2.address}/follow/"
        self.client.post(url)

        # get feed of user 1
        url = "/api/feed/"
        resp = self.client.get(url)

        # assert user 1 feed has the posts of user 1 and user 2
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)
        self.assertEqual(
            resp.data["results"][0]["author"]["address"],
            self.test_signer.address
        )
        self.assertEqual(
            resp.data["results"][1]["author"]["address"],
            self.test_signer_2.address
        )


class ExploreTests(BaseTest):
    """
    Test behavior around explore page.
    """

    def test_profiles_by_follower_count(self):
        """
        Assert that the top 8 profiles by follower count are returned.
        """
        # set up test
        # create 10 profiles
        signers = self._create_users(10)

        # make each user follow the remaining users
        # so user 1 follows users 2-10
        # user 2 follows users 3-10, etc
        for i in range(10):
            self._do_login(signers[i])
            for j in range(i+1, 10):
                url = f"/api/{signers[j].address}/follow/"
                self.client.post(url)

        # make request to fetch explore page profiles
        self._do_logout()
        url = "/api/explore/"
        resp = self.client.get(url)

        # make assertions
        # assert that the top 8 profiles are returned
        self.assertEqual(len(resp.data), 8)

        # assert that the explore profiles are sorted
        # in order from most followers to least
        # user 10 should have the most followers
        # user 3 should have the least followers
        for i in range(8):
            self.assertEqual(resp.data[i]["address"], signers[9-i].address)


class NotificationTests(BaseTest):
    """
    Test behavior around notifications.
    """

    def test_get_notifs(self):
        """
        Assert that a logged in user can get a list of notifications.
        """
        # set up test
        # user 1 logs in
        self._do_login(self.test_signer)

        # make request for notifications
        url = "/api/notifications/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"], [])

    def test_get_notifs_unauthed(self):
        """
        Assert that a logged out user cannot get a list of notifications.
        """
        # set up test

        # make request for notifications
        url = "/api/notifications/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 403)

    def test_comment_on_post_notifs(self):
        """
        Assert that a user gets a notification when
        another user comments on their post.
        """
        # set up test
        # user 1 creates a post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        self._do_logout()

        # user 2 comments on user 1's post
        self._do_login(self.test_signer_2)
        self._create_comment(post_id, text="hello")
        self._do_logout()

        # make request to get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)

        # make assertions
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        notification = resp.data["results"][0]
        self.assertEqual(notification["viewed"], False)
        event = notification["events"]["commentOnPostEvent"]
        self.assertEqual(event["post"], post_id)
        self.assertEqual(
            event["commentor"]["address"],
            self.test_signer_2.address
        )

    def test_mentioned_in_post_notif(self):
        """
        Assert that a user gets a notification when
        another user mentions them in a post.
        """
        # set up test
        # create users 1 and 2
        self._do_login(self.test_signer)
        self._do_login(self.test_signer_2)
        # user 2 tags user 1 in a post
        tagged = [self.test_signer.address]
        resp = self._create_post(
            tagged_users=tagged
        )
        post_id = resp.data["id"]

        # make request to get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)

        # assert that user 1 has a notification for post mention
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        notification = resp.data["results"][0]
        self.assertEqual(notification["viewed"], False)
        event = notification["events"]["mentionedInPostEvent"]
        self.assertEqual(event["post"], post_id)
        self.assertEqual(
            event["mentionedBy"]["address"],
            self.test_signer_2.address
        )

    def test_mentioned_in_comment_notif(self):
        """
        Assert that a user gets a notification when
        another user mentions them in a comment.
        """
        # set up test
        # create users 1 and 2
        self._do_login(self.test_signer)
        self._do_login(self.test_signer_2)
        # user 1 creates a post and a comment
        # where they mention user 2
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        self._create_comment(
            post_id,
            text="hello user 2",
            tagged_users=[self.test_signer_2.address]
        )
        self._do_logout()

        # make request to get user 2's notifications
        self._do_login(self.test_signer_2)
        url = "/api/notifications/"
        resp = self.client.get(url)

        # assert that user 2 has a notification for the comment mention
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        notification = resp.data["results"][0]
        self.assertEqual(notification["viewed"], False)
        event = notification["events"]["mentionedInCommentEvent"]
        self.assertEqual(event["post"], post_id)
        self.assertEqual(
            event["mentionedBy"]["address"],
            self.test_signer.address
        )

    def test_follow_notif(self):
        """
        Assert that a user gets a notification when
        another user follows them.
        """
        # set up test
        # create users 1 and 2
        self._do_login(self.test_signer)
        self._do_login(self.test_signer_2)
        # user 2 follows user 1
        self._follow_user(self.test_signer.address)

        # make request to get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)

        # assert that user 1 has a notification for the follow
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        notification = resp.data["results"][0]
        self.assertEqual(notification["viewed"], False)
        event = notification["events"]["followedEvent"]
        self.assertEqual(
            event["followedBy"]["address"],
            self.test_signer_2.address
        )

    def test_mark_notifs_as_viewed(self):
        """
        Assert that a user can mark notification as viewed.
        """
        # set up test
        # user 1 creates a post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # user 2 comments on user 1's post twice
        self._do_login(self.test_signer_2)
        self._create_comment(post_id, text="hello")
        self._create_comment(post_id, text="friend")
        self._do_logout()

        # get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)
        notif_ids = [notif['id'] for notif in resp.data["results"]]

        # make request to mark notifications as viewed
        url = "/api/notifications/"
        data = {"notifications": notif_ids}
        resp = self.client.put(url, data)

        # assert that notifications are now viewed
        self.assertEqual(resp.status_code, 200)
        for notif in resp.data:
            self.assertTrue(notif["viewed"])

    def test_mark_notifs_as_viewed_unauthed(self):
        """
        Assert that an unauthenticated user
        cannot mark notifications as viewed.
        """
        # set up test
        # user 1 creates a post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # user 2 comments on user 1's post
        self._do_login(self.test_signer_2)
        self._create_comment(post_id, text="hello")

        # get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)
        notif_ids = [notif['id'] for notif in resp.data["results"]]

        # make unauthenticated request to mark notifs as viewed
        self._do_logout()
        url = "/api/notifications/"
        data = {"notifications": notif_ids}
        resp = self.client.put(url, data)

        # assert 403
        self.assertEqual(resp.status_code, 403)

    def test_mark_notifs_as_viewed_for_others(self):
        """
        Assert that a user cannot mark
        another user's notifications as viewed.
        """
        # set up test
        # user 1 creates a post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # user 2 comments on user 1's post
        self._do_login(self.test_signer_2)
        self._create_comment(post_id, text="hello")
        self._do_logout()

        # get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)
        notif_ids = [notif['id'] for notif in resp.data["results"]]

        # make request as user 2 to mark user 1's notifications as viewed
        self._do_logout()
        self._do_login(self.test_signer_2)
        url = "/api/notifications/"
        data = {"notifications": notif_ids}
        resp = self.client.put(url, data)

        # assert that user 2 gets a 403
        self.assertEqual(resp.status_code, 403)

    def test_liked_your_post_notifs(self):
        """
        Assert that a user gets a notification when
        another user likes their post.
        """
        # set up test
        # user 1 creates a post
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # user 2 likes user 1's post
        self._do_login(self.test_signer_2)
        url = f"/api/post/{post_id}/likes/"
        resp = self.client.post(url)

        # assert that user 1 received a notification
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)
        notif = resp.data["results"][0]
        event = notif["events"]["likedPostEvent"]
        self.assertEqual(
            event["likedBy"]["address"],
            self.test_signer_2.address
        )

    def test_liked_your_comment_notifs(self):
        """
        Assert that a user gets a notification when
        another user likes their comment.
        """
        # set up test
        # user 1 creates a post and comment
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]
        resp = self._create_comment(post_id, "hello")
        comment_id = resp.data["id"]

        # user 2 likes user 1's comment
        self._do_login(self.test_signer_2)
        url = f"/api/posts/{post_id}/comments/{comment_id}/likes/"
        resp = self.client.post(url)

        # assert that user 1 received a notification
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)
        notif = resp.data["results"][0]
        event = notif["events"]["likedCommentEvent"]
        self.assertEqual(
            event["likedBy"]["address"],
            self.test_signer_2.address
        )
        self.assertEqual(event["comment"], comment_id)
        self.assertEqual(event["post"], post_id)

    def test_repost_notif(self):
        """
        Assert that a user gets a notification when
        another user reposts their post.
        """
        # set up test
        # create post by user 1
        self._do_login(self.test_signer)
        resp = self._create_post()
        post_id = resp.data["id"]

        # repost user1's post by user2
        self._do_login(self.test_signer_2)
        resp = self._repost(post_id)
        repost_id = resp.data["id"]

        # make request to get user 1's notifications
        self._do_login(self.test_signer)
        url = "/api/notifications/"
        resp = self.client.get(url)

        # assert that user 1 has a notification for the repost
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        notification = resp.data["results"][0]
        event = notification["events"]["repostEvent"]
        self.assertEqual(event["repost"], repost_id)
        self.assertEqual(
            event["repostedBy"]["address"],
            self.test_signer_2.address
        )
