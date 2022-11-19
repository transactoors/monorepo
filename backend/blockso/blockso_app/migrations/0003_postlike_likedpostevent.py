# Generated by Django 4.1.1 on 2022-11-19 15:29

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('blockso_app', '0002_post_tagged_users_mentionedinpostevent'),
    ]

    operations = [
        migrations.CreateModel(
            name='PostLike',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('liker', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='post_likes', to='blockso_app.profile')),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='likes', to='blockso_app.post')),
            ],
            options={
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='LikedPostEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('liked_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='blockso_app.profile')),
                ('notification', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='liked_post_event', to='blockso_app.notification')),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='blockso_app.post')),
            ],
        ),
    ]
