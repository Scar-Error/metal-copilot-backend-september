from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from rfq.email_ingestion_service import EmailIngestionService

User = get_user_model()


class Command(BaseCommand):
    help = 'Process RFQ emails from Outlook and create Order records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID to process emails for (default: first user)'
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=1,
            help='Number of days back to check for emails (default: 1)'
        )

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        days_back = options.get('days_back', 1)

        self.stdout.write(f'Processing RFQ emails from last {days_back} days...')

        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User with ID {user_id} not found'))
                return
        else:
            user = User.objects.first()
            if not user:
                self.stdout.write(self.style.ERROR('No users found in database'))
                return

        self.stdout.write(f'Processing emails for user: {user.username}')

        ingestion_service = EmailIngestionService(user)
        result = ingestion_service.check_and_process_new_emails(days_back=days_back)

        if result['success']:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully processed {result["processed"]} RFQ emails'
                )
            )
            if result['errors']:
                self.stdout.write(
                    self.style.WARNING(
                        f'Errors encountered: {len(result["errors"])}'
                    )
                )
                for error in result['errors']:
                    self.stdout.write(f'  - {error}')
        else:
            self.stdout.write(
                self.style.ERROR(
                    f'Failed to process emails: {result["errors"]}'
                )
            )
