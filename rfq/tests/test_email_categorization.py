from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from rfq.models import EmailMessage, EmailThread

User = get_user_model()

pytestmark = pytest.mark.django_db


def make_thread(*categories, sender_email='supplier@example.com'):
    """Build a thread whose messages get classified in the given order."""
    user = User.objects.create_user(
        username=f'cat-tester-{uuid.uuid4().hex[:8]}', password='pw'
    )
    thread = EmailThread.objects.create(
        conversation_id=f'conv-{uuid.uuid4().hex[:12]}',
        subject='Thread subject',
        user=user,
    )
    base = timezone.now()
    messages = []
    for index, category in enumerate(categories):
        messages.append(
            EmailMessage.objects.create(
                thread=thread,
                message_id=f'msg-{thread.conversation_id}-{index}',
                subject=f'Message {index}',
                sender_email=sender_email,
                body='body',
                received_at=base + timezone.timedelta(minutes=index),
            )
        )
    return thread, messages


def classify_as(*results):
    """Patch the classifier so successive calls return the given results."""
    iterator = iter(results)

    def classify(_email):
        try:
            return next(iterator)
        except StopIteration:
            return 'other'

    return patch('rfq.ai_classifier.AiEmailClassifier.classify', side_effect=classify)


@pytest.fixture
def client():
    api = APIClient()
    api.force_authenticate(user=User.objects.create_user(username='api-tester', password='pw'))
    return api


def categorize(client, thread):
    return client.post(f'/api/rfq/email-threads/{thread.id}/categorize/')


class TestPerMessageTags:
    def test_each_message_keeps_its_own_tag(self, client) -> None:
        thread, messages = make_thread('rfq', 'quotation', 'po')

        with classify_as('rfq', 'quotation', 'po'):
            response = categorize(client, thread)

        assert response.status_code == 200
        tags = list(
            EmailMessage.objects.filter(thread=thread)
            .order_by('received_at')
            .values_list('category', flat=True)
        )
        assert tags == ['rfq', 'quotation', 'po']

    def test_response_echoes_per_message_tags(self, client) -> None:
        thread, messages = make_thread('rfq', 'other')

        with classify_as('rfq', 'other'):
            response = categorize(client, thread)

        payload = {m['message_id']: m['category'] for m in response.data['messages']}
        assert payload == {messages[0].message_id: 'rfq', messages[1].message_id: 'other'}


class TestThreadTagUsesHighestPriority:
    def test_po_tag_wins_over_everything(self, client) -> None:
        thread, _ = make_thread('other', 'rfq', 'quotation', 'po')

        with classify_as('other', 'rfq', 'quotation', 'po'):
            response = categorize(client, thread)

        assert response.data['category'] == 'po'
        thread.refresh_from_db()
        assert thread.category == 'po'

    def test_quotation_tag_wins_over_rfq(self, client) -> None:
        thread, _ = make_thread('rfq', 'quotation')

        with classify_as('rfq', 'quotation'):
            response = categorize(client, thread)

        assert response.data['category'] == 'quotation'

    def test_rfq_tag_wins_over_other(self, client) -> None:
        thread, _ = make_thread('other', 'rfq')

        with classify_as('other', 'rfq'):
            response = categorize(client, thread)

        assert response.data['category'] == 'rfq'

    def test_all_other_yields_other(self, client) -> None:
        thread, _ = make_thread('other', 'other')

        with classify_as('other', 'other'):
            response = categorize(client, thread)

        assert response.data['category'] == 'other'
        thread.refresh_from_db()
        assert thread.category == 'other'

    def test_garbage_classifier_output_becomes_other(self, client) -> None:
        thread, _ = make_thread('rfq')

        with classify_as('definitely not a category'):
            response = categorize(client, thread)

        assert response.data['category'] == 'other'


class TestThreadLifecycleAcrossColumns:
    """Synced holds untagged threads; analysis moves them to Categorized."""

    def test_categorize_moves_thread_into_categorized(self, client) -> None:
        thread, _ = make_thread('rfq', 'po')
        assert thread.stage == 'synced'

        with classify_as('rfq', 'po'):
            categorize(client, thread)

        thread.refresh_from_db()
        assert thread.stage == 'categorized'
        assert thread.category == 'po'

    def test_categorized_thread_stays_put(self, client) -> None:
        # Analysis must not move a thread back out of Categorized, and reading
        # the board must not move it either.
        thread, _ = make_thread('rfq')

        with classify_as('rfq'):
            categorize(client, thread)

        client.get('/api/rfq/email-threads/')
        client.get('/api/rfq/email-threads/?stage=categorized')
        client.get(f'/api/rfq/email-threads/{thread.id}/')

        thread.refresh_from_db()
        assert thread.stage == 'categorized'
        assert thread.category == 'rfq'

    def test_synced_thread_has_no_tag(self, client) -> None:
        # The Synced column is untouched by analysis: an unanalyzed thread shows
        # no thread tag and none on its individual messages.
        thread, messages = make_thread('rfq', 'po')

        assert thread.stage == 'synced'
        assert thread.category == ''

        card = next(
            r for r in client.get('/api/rfq/email-threads/').data if r['id'] == thread.id
        )
        assert card['category'] == ''
        assert [m['category'] for m in card['messages']] == ['', '']

    def test_synced_column_contains_only_untagged_threads(self, client) -> None:
        untagged, _ = make_thread('rfq')
        analyzed, _ = make_thread('rfq', sender_email='a@example.com')

        with classify_as('rfq'):
            categorize(client, analyzed)

        synced = client.get('/api/rfq/email-threads/?stage=synced').data
        assert any(r['id'] == untagged.id for r in synced)
        assert not any(r['id'] == analyzed.id for r in synced)

    def test_recategorizing_keeps_thread_categorized(self, client) -> None:
        thread, _ = make_thread('rfq', 'po')

        with classify_as('rfq', 'po'):
            categorize(client, thread)
        with classify_as('other', 'other'):
            categorize(client, thread)

        thread.refresh_from_db()
        assert thread.category == 'other'
        assert thread.stage == 'categorized'


class TestRecomputeCategory:
    """The thread tag is derived from message tags, never set independently."""

    def test_untagged_messages_leave_thread_untagged(self, client) -> None:
        thread, messages = make_thread('rfq', 'po')
        assert thread.recompute_category() is None
        thread.refresh_from_db()
        assert thread.category == ''

    def test_derives_highest_priority_tag(self) -> None:
        thread, messages = make_thread('rfq', 'po', 'other')
        for msg, tag in zip(messages, ['other', 'rfq', 'po']):
            msg.category = tag
            msg.save(update_fields=['category'])

        assert thread.recompute_category() == 'po'
        thread.refresh_from_db()
        assert thread.category == 'po'

    def test_repairs_a_cleared_thread_tag(self) -> None:
        thread, messages = make_thread('rfq', 'quotation')
        for msg, tag in zip(messages, ['rfq', 'quotation']):
            msg.category = tag
            msg.save(update_fields=['category'])
        EmailThread.objects.filter(pk=thread.pk).update(category='')

        assert thread.recompute_category() == 'quotation'
        thread.refresh_from_db()
        assert thread.category == 'quotation'

    def test_save_false_does_not_write(self) -> None:
        thread, messages = make_thread('po')
        messages[0].category = 'po'
        messages[0].save(update_fields=['category'])
        EmailThread.objects.filter(pk=thread.pk).update(category='')

        assert thread.recompute_category(save=False) == 'po'
        thread.refresh_from_db()
        assert thread.category == ''

    def test_ignores_untagged_messages_when_deriving(self) -> None:
        thread, messages = make_thread('rfq', 'po')
        messages[0].category = 'rfq'
        messages[0].save(update_fields=['category'])
        # Second message stays blank, as freshly pulled mail would be.

        assert thread.recompute_category() == 'rfq'


class TestTagsVisibleOnCardAndInThread:
    def test_card_carries_the_thread_tag(self, client) -> None:
        thread, _ = make_thread('rfq', 'po')

        with classify_as('rfq', 'po'):
            categorize(client, thread)

        listing = client.get('/api/rfq/email-threads/')
        card = next(r for r in listing.data if r['id'] == thread.id)
        assert card['category'] == 'po'
        assert card['stage'] == 'categorized'

    def test_card_carries_every_individual_message_tag(self, client) -> None:
        # The board is what the user is looking at, so it has to carry the
        # per-message tags and not just the thread's top tag.
        thread, messages = make_thread('rfq', 'quotation', 'po')

        with classify_as('rfq', 'quotation', 'po'):
            categorize(client, thread)

        card = next(
            r for r in client.get('/api/rfq/email-threads/').data if r['id'] == thread.id
        )
        by_message = {m['message_id']: m['category'] for m in card['messages']}
        assert by_message == {
            messages[0].message_id: 'rfq',
            messages[1].message_id: 'quotation',
            messages[2].message_id: 'po',
        }

    def test_card_omits_message_bodies(self, client) -> None:
        # The board must stay small: tags yes, bodies no.
        thread, _ = make_thread('rfq', 'po')

        with classify_as('rfq', 'po'):
            categorize(client, thread)

        card = next(
            r for r in client.get('/api/rfq/email-threads/').data if r['id'] == thread.id
        )
        for message in card['messages']:
            assert 'body' not in message
            assert 'body_preview' not in message
            assert 'category' in message

    def test_board_tags_do_not_n_plus_one(self, client) -> None:
        # Adding messages to the board payload must not turn into one query per
        # message. The query count has to stay flat as threads are added,
        # otherwise every board load would hammer the database.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def query_count():
            with CaptureQueriesContext(connection) as ctx:
                response = client.get('/api/rfq/email-threads/')
            assert response.status_code == 200
            return len(ctx.captured_queries)

        thread, _ = make_thread('rfq', 'po', sender_email='one@example.com')
        with classify_as('rfq', 'po'):
            categorize(client, thread)
        baseline = query_count()

        for index in range(4):
            extra, _ = make_thread('rfq', 'po', sender_email=f'bulk{index}@example.com')
            with classify_as('rfq', 'po'):
                categorize(client, extra)

        assert query_count() == baseline

    def test_thread_detail_carries_every_message_tag(self, client) -> None:
        thread, messages = make_thread('rfq', 'quotation', 'po')

        with classify_as('rfq', 'quotation', 'po'):
            categorize(client, thread)

        detail = client.get(f'/api/rfq/email-threads/{thread.id}/')
        assert detail.status_code == 200
        assert detail.data['category'] == 'po'

        by_message = {m['message_id']: m['category'] for m in detail.data['messages']}
        assert by_message == {
            messages[0].message_id: 'rfq',
            messages[1].message_id: 'quotation',
            messages[2].message_id: 'po',
        }


class TestRecomputeThreadTagsCommand:
    def test_repairs_cleared_thread_tag(self) -> None:
        thread, messages = make_thread('rfq', 'po')
        for msg, tag in zip(messages, ['rfq', 'po']):
            msg.category = tag
            msg.save(update_fields=['category'])
        EmailThread.objects.filter(pk=thread.pk).update(category='')

        call_command('recompute_thread_tags')

        thread.refresh_from_db()
        assert thread.category == 'po'

    def test_promotes_tagged_thread_to_categorized_on_request(self) -> None:
        thread, messages = make_thread('po')
        messages[0].category = 'po'
        messages[0].save(update_fields=['category'])

        call_command('recompute_thread_tags', fix_stage=True)

        thread.refresh_from_db()
        assert thread.stage == 'categorized'
        assert thread.category == 'po'

    def test_leaves_stage_alone_without_fix_stage(self) -> None:
        # A tagged thread sitting in Synced is the normal "new message arrived,
        # awaiting analysis" state, so the command must not move it unasked.
        thread, messages = make_thread('po')
        messages[0].category = 'po'
        messages[0].save(update_fields=['category'])

        call_command('recompute_thread_tags')

        thread.refresh_from_db()
        assert thread.stage == 'synced'
        assert thread.category == 'po'

    def test_never_moves_a_categorized_thread_back_to_synced(self) -> None:
        # The whole point of the Categorized column: once analyzed, a thread
        # stays there until a new message arrives. No bulk tool may undo that.
        thread, messages = make_thread('po')
        messages[0].category = 'po'
        messages[0].save(update_fields=['category'])
        EmailThread.objects.filter(pk=thread.pk).update(stage='categorized')

        call_command('recompute_thread_tags', fix_stage=True)

        thread.refresh_from_db()
        assert thread.stage == 'categorized'

    def test_leaves_never_analyzed_threads_untagged(self) -> None:
        thread, _ = make_thread('rfq')  # tags never assigned

        call_command('recompute_thread_tags')

        thread.refresh_from_db()
        assert thread.category == ''

    def test_dry_run_writes_nothing(self) -> None:
        thread, messages = make_thread('rfq', 'po')
        for msg, tag in zip(messages, ['rfq', 'po']):
            msg.category = tag
            msg.save(update_fields=['category'])
        EmailThread.objects.filter(pk=thread.pk).update(category='')

        call_command('recompute_thread_tags', dry_run=True)

        thread.refresh_from_db()
        assert thread.category == ''
