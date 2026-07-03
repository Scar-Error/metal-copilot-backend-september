import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('rfq_system')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.beat_schedule = {
    # 'process-emails-every-1-minute': {
    #     'task': 'rfq.tasks.monitor_emails_for_rfqs',
    #     'schedule': crontab(minute='*/1'),
    # },
    'cleanup-old-attachments-daily': {
        'task': 'rfq.tasks.cleanup_old_attachments',
        'schedule': crontab(hour=3, minute=0),
    },
}

app.conf.task_routes = {
    'rfq.tasks.monitor_emails_for_rfqs': {'queue': 'email_polling'},
    'rfq.tasks.process_user_emails': {'queue': 'email_polling'},
    'rfq.tasks.sync_with_business_central': {'queue': 'email_polling'},
    'rfq.tasks.process_rfq_with_ai': {'queue': 'ai_processing'},
    'rfq.tasks.dispatch_to_supplier': {'queue': 'email_dispatch'},
    'rfq.tasks.cleanup_old_attachments': {'queue': 'housekeeping'},
}
