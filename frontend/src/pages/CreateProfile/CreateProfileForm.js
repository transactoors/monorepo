import React, { useEffect } from 'react'
import { Container, Form, Button, Row, Col } from 'react-bootstrap'
import { baseAPI, getCookie } from '../../utils'
import NftForm from './NftForm'
import { useAccount } from 'wagmi'
import FileUpload from './FileUpload'

function CreateProfileForm({ profile, setProfile, initialState, getUser }) {

    const { isConnected, address } = useAccount();

     // Form State Update
     const handleChange = (event) => {
      const { name, value } = event.target
      setProfile(prevValue => {
          return {
              ...prevValue,
              [name]: value
          }
      })
  } 
  
  // Form Submission Function
  const handleSubmit = async () => {
      if(!isConnected) return
      const url = `${baseAPI}/${address}/profile/`
      const formRes = await fetch(url, {
          method: 'POST',
          body: JSON.stringify(profile),
          headers: {
              'Content-Type': 'application/json',
              'X-CSRFTOKEN': getCookie('csrftoken')
            },
            credentials: 'include'
      })
      
      if(formRes.status === 200 || 201) {
        console.log('successfully posted data')
        setProfile(initialState)
      } else console.log('error posting data')
 
  }

  const checkForProfile = async () => {
    const res = getUser()
    if(res.profile === !null) {
      // Give popup error saying profile exists
      console.log('profile already exists') 
      return
    } else console.log('profile does not exist')
  }
  
  return (
    <>
    <Container className='p-3'>
        <Form>
        
        <FileUpload
        profile={profile}
        setProfile={setProfile}/>

        <NftForm
        profile={profile}
        setProfile={setProfile}/>

        <Form.Group className="mb-3 border p-3">
            <Form.Label>Bio</Form.Label>
            <Form.Control onChange={handleChange} name="bio" value={profile.name} type="text" placeholder="" />
            <Form.Text className="text-muted">
            Tell us a little about yourself.
            </Form.Text>
        </Form.Group>

        <div className="border p-3">
            <h3>Add Socials (optional):</h3>
            <Form.Group className="mb-3" controlId="website">
            <Form.Label>Website</Form.Label>
            <Form.Control onChange={handleChange} name="website" value={profile.socials.name} type="text" size="sm" placeholder="" />
            </Form.Group>

            <Row>

                <Col>
                    <Form.Group className="mb-3" controlId="">
                    <Form.Label>Twitter</Form.Label>
                    <Form.Control onChange={handleChange} name="twitter" value={profile.socials.name} type="text" size="sm" placeholder="" />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="">
                    <Form.Label>Telegram</Form.Label>
                    <Form.Control onChange={handleChange} name="telegram" value={profile.socials.name} type="text" size="sm" placeholder="" />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="">
                    <Form.Label>Discord</Form.Label>
                    <Form.Control onChange={handleChange} name="discord" value={profile.socials.name} type="text" size="sm" placeholder="" />
                    </Form.Group>
                </Col>

                <Col>
                    <Form.Group className="mb-3" controlId="">
                    <Form.Label>Opensea</Form.Label>
                    <Form.Control onChange={handleChange} name="opensea" value={profile.socials.name} type="text" size="sm" placeholder="" />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="">
                        <Form.Label>LooksRare</Form.Label>
                        <Form.Control onChange={handleChange} name="looksrare" value={profile.socials.name} type="text" size="sm" placeholder="" />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="">
                        <Form.Label>Snapshot</Form.Label>
                        <Form.Control onChange={handleChange} name="snapshot" value={profile.socials.name} type="text" size="sm" placeholder="" />
                    </Form.Group>
                </Col>

             </Row>
        </div>
        <Button disabled={!isConnected} variant="primary" onClick={handleSubmit}>
            Submit
        </Button> 
            {!isConnected ? <Form.Text className="text-muted p-3">
            Please connect to Metamask before submitting.
            </Form.Text> : '' }
        </Form>
    </Container>
</>
)
}

export default CreateProfileForm