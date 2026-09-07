from django.db import migrations


def backfill_attachment_urls(apps, schema_editor):
    Order = apps.get_model('rfq', 'Order')
    OrderAttachment = apps.get_model('rfq', 'OrderAttachment')
    for order in Order.objects.all():
        urls = list(
            OrderAttachment.objects
            .filter(order=order)
            .exclude(file_url='')
            .order_by('uploaded_at')
            .values_list('file_url', flat=True)
        )
        if urls:
            order.attachment_urls = urls
            order.save(update_fields=['attachment_urls'])


def undo_backfill(apps, schema_editor):
    Order = apps.get_model('rfq', 'Order')
    Order.objects.update(attachment_urls=[])


class Migration(migrations.Migration):

    dependencies = [
        ('rfq', '0012_order_attachment_urls'),
    ]

    operations = [
        migrations.RunPython(backfill_attachment_urls, undo_backfill),
    ]
