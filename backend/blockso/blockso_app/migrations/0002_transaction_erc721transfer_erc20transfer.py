# Generated by Django 4.1.1 on 2022-09-16 10:38

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('blockso_app', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chain_id', models.PositiveSmallIntegerField()),
                ('tx_hash', models.CharField(max_length=255)),
                ('block_signed_at', models.DateTimeField()),
                ('tx_offset', models.PositiveSmallIntegerField()),
                ('successful', models.BooleanField()),
                ('from_address', models.CharField(max_length=255)),
                ('to_address', models.CharField(max_length=255)),
                ('value', models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name='ERC721Transfer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contract_address', models.CharField(max_length=255)),
                ('contract_name', models.CharField(max_length=255)),
                ('contract_ticker', models.CharField(max_length=255)),
                ('logo_url', models.URLField()),
                ('from_address', models.CharField(max_length=255)),
                ('to_address', models.CharField(max_length=255)),
                ('token_id', models.PositiveIntegerField()),
                ('tx', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='erc721_transfers', to='blockso_app.transaction')),
            ],
        ),
        migrations.CreateModel(
            name='ERC20Transfer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contract_address', models.CharField(max_length=255)),
                ('contract_name', models.CharField(max_length=255)),
                ('contract_ticker', models.CharField(max_length=255)),
                ('logo_url', models.URLField()),
                ('from_address', models.CharField(max_length=255)),
                ('to_address', models.CharField(max_length=255)),
                ('amount', models.PositiveBigIntegerField()),
                ('decimals', models.PositiveSmallIntegerField()),
                ('tx', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='erc20_transfers', to='blockso_app.transaction')),
            ],
        ),
    ]