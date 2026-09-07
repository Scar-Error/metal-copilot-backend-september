from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rfq', '0017_processedemail'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='quotation_email_sent',
        ),
        migrations.RemoveField(
            model_name='order',
            name='supplier_email',
        ),
        migrations.RemoveField(
            model_name='order',
            name='supplier_email_error',
        ),
        migrations.RemoveField(
            model_name='order',
            name='supplier_email_sent',
        ),
        migrations.RemoveField(
            model_name='order',
            name='supplier_email_sent_at',
        ),
        migrations.RemoveField(
            model_name='ordersupplierassignment',
            name='email_error',
        ),
        migrations.RemoveField(
            model_name='ordersupplierassignment',
            name='email_sent',
        ),
        migrations.RemoveField(
            model_name='ordersupplierassignment',
            name='email_sent_at',
        ),
    ]