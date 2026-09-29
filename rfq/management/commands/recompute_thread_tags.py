"""Reconcile every EmailThread's tag with the tags on its individual messages.

The thread tag is derived data: it is the highest-priority tag among the
thread's messages. That derivation can drift out of step with the messages it
summarises — for example if a thread's tag was cleared, or was written by an
older code path that behaved differently.

This command recomputes the tags from the messages that are already tagged. It
makes no AI calls, so it is safe and instant to run as often as needed.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from rfq.models import EmailMessage, EmailThread


class Command(BaseCommand):
    help = 'Recompute EmailThread.category from each thread\u2019s message tags.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--user-id',
            type=int,
            default=None,
            help='Only repair threads belonging to this user.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would change without writing anything.',
        )
        parser.add_argument(
            '--fix-stage',
            action='store_true',
            help=(
                'Also set stage=categorized on any thread that carries a tag but '
                'is still sitting in Synced. Off by default, because the stage is '
                'only meant to be moved by the categorize endpoint.'
            ),
        )

    def handle(self, *args, **options) -> None:
        dry_run = options['dry_run']
        fix_stage = options['fix_stage']

        threads = EmailThread.objects.all().order_by('id')
        if options['user_id']:
            threads = threads.filter(user_id=options['user_id'])

        # Only threads with at least one already-tagged message have anything to
        # derive from. Untouched threads keep category='' ("not analyzed yet")
        # rather than being silently downgraded to 'other'.
        threads = threads.annotate(
            has_tagged_message=Exists(
                EmailMessage.objects.filter(
                    thread=OuterRef('pk'),
                ).exclude(category='')
            )
        ).filter(has_tagged_message=True)

        repaired = 0
        already_correct = 0
        skipped = 0
        promoted = 0

        for thread in threads:
            # Capture the stored value first: recompute_category() assigns the
            # resolved tag onto the instance, so comparing afterwards would
            # always report "no change".
            previous_category = thread.category
            expected = thread.recompute_category(save=False)
            if expected is None:
                skipped += 1
                continue

            category_changed = previous_category != expected
            # Only with --fix-stage, and only in one direction. A categorized
            # thread is never moved back to Synced, and a thread is never moved
            # between columns without being asked.
            stage_stale = fix_stage and thread.stage == 'synced'

            if not category_changed and not stage_stale:
                already_correct += 1
                continue

            if stage_stale:
                thread.stage = 'categorized'

            if not dry_run:
                thread.save(update_fields=['category', 'stage', 'updated_at'])

            if category_changed:
                repaired += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'  thread {thread.id} ({thread.conversation_id[-16:]}): '
                        f'{previous_category!r} -> {expected!r}'
                    )
                )
            if stage_stale:
                promoted += 1
                if not category_changed:
                    self.stdout.write(
                        f'  thread {thread.id} ({thread.conversation_id[-16:]}): '
                        f'stage synced -> categorized'
                    )

        prefix = 'Would repair' if dry_run else 'Repaired'
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefix} {repaired} thread tag(s)'
                + (f'; promoted {promoted} to Categorized' if fix_stage else '')
                + f'; {already_correct} already correct; {skipped} skipped.'
            )
        )
