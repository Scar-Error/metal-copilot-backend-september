from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rfq', '0027_orderaimetadata_orderbusinesscentral_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='supplier',
        ),
        migrations.RemoveField(
            model_name='order',
            name='suppliers',
        ),
        migrations.RemoveField(
            model_name='order',
            name='probability',
        ),
        migrations.DeleteModel(
            name='OrderSupplierAssignment',
        ),
    ]
