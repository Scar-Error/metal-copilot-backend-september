# RFQ Extraction & Orchestration — Reference

This document explains how incoming supplier/customer emails are discovered,
classified, extracted, and turned into `Order` records. It is written for an
AI agent (or a new developer) so you can understand, extend, or debug the
pipeline without re-reading every source file.

> This document reflects the **current** state of the code (post-refactor):
> classification and extraction are **AI-only**, Business Central **automated sync
> is disabled by default**, and **outbound email sending has been removed** (no
> email is sent to suppliers or customers). Email **attachments are part of the
> pipeline**: PDF/DOCX text is extracted, image attachments are kept temporarily
> and handed to the AI.
>
> **Celery has been removed.** There is no background worker and no automated
> polling/auto-save: email is ingested **manually only** via the "Pull Emails"
> action (`POST /api/rfq/monitor/emails/pull/`, synchronous) in the Deals UI,
> which drives the exact same pipeline below. RFQ creation from a thread happens
> manually through AI analysis in the UI (see `EmailThreadViewSet.categorize`).

---

## 1. High-level flow

```
Manual "Pull Emails" (POST /api/rfq/monitor/emails/pull/)
    └─ pull_emails() (views_email.py, synchronous)
        └─ EmailIngestionService(user).check_and_process_new_emails(days_back=1)
            └─ EmailIngestionOrchestrator.poll_new_emails(days_back=1)
                        ├─ GraphEmailProvider.fetch_emails(limit=50, days_back=1)
                        ├─ AiEmailClassifier.classify(email)      → rfq | po | quotation | other
                        │    └─ 'other' → skipped (nothing created)
                        └─ _process_one_email(email, classification)
                             ├─ bounce check → skip
                             ├─ find/create Order
└─ per-classification handler:
                                   rfq       → _handle_rfq_po  (extract, supplier task, BC quote)
                                   po        → _handle_po      (extract, type=purchase_order, BC sales order + PO)
                                   quotation → _handle_quotation (match items, prices)
        └─ GraphEmailProvider.mark_as_processed(msg_id)  ← MAPI marker (dedup)
```

The email pulling is manual and synchronous (see above); there is no background
scheduler. The orchestrator processes email for the requesting user (and any
user with a Microsoft OAuth account connected).

---

## 2. Key concepts

- **`EmailMessage`** (`rfq/interfaces.py`) — TypedDict shape that flows through
  the pipeline. Fields: `id` (message id, used for dedup), `subject`,
  `sender_name`, `sender_email`, `received_at`, `body`, `conversation_id`
  (Outlook conversation id, used to dedupe the failure task), plus
  `has_attachments` and `attachments` (list of `AttachmentData`:
  `id`, `name`, `size`, `content_type`).
- **`AttachmentData`** (`rfq/interfaces.py`) — TypedDict describing one email
  attachment. The orchestrator downloads the bytes (see §5a) for document text
  extraction or temporary image storage.
- **`EmailClassification`** — `Literal['rfq', 'po', 'quotation', 'other']`
  (`rfq/interfaces.py:10`). This is the only classification vocabulary.
- **`EmailClassifier`** (Protocol) — anything with
  `classify(email) -> EmailClassification`.
- **`DataExtractor`** (Protocol) — anything with
  `extract(text, source_label='', is_quotation=False) -> Optional[ExtractedRfqData]`.
- **`EmailProvider`** (Protocol) — `fetch_emails`, `get_email_by_id`,
  `mark_as_processed`, `get_user_email`.

All three abstractions are injected into the orchestrator (`orchestrator.py:37`),
which is what makes the pipeline unit-testable with fakes.

---

## 3. Email discovery (Graph API)

`microsoft_auth/graph_api.py` → `GraphEmailProvider` implements `EmailProvider`.

- `fetch_emails(limit=50, days_back=1)`:
  - Finds the mailbox folder named `inbox` (falls back to matching `Inbox` by
    display name).
  - Queries `/messages` with `$filter` on `receivedDateTime` (`days_back`
    window, i.e. last 1 day), `$top=limit`, `$select` including
    `id, subject, from, receivedDateTime, body, bodyPreview, conversationId,
    hasAttachments` and `$expand=attachments($select=id,name,size,contentType)`.
  - Normalizes each raw message into an `EmailMessage` (drops non-email
    senders, e.g. empty `from` entries) and parses the attachment metadata
    into `AttachmentData` entries.
  - ⚠️ There is currently a **temporary date filter** ("only process emails
    received after 31 July") that must be removed when going live — see the comment
    in `fetch_emails`.
- `get_attachments(email_id)` — returns attachment metadata for a message.
- `download_attachment(email_id, attachment_id)` — downloads raw bytes via
  `/messages/{id}/attachments/{attachment_id}/$value`.
- `mark_as_processed(email_id)` — writes a MAPI **named property** on the
  message: `PROCESSED_PROPERTY_ID = 'String {00020329-0000-0000-C000-000000000046} Name RFQProcessed'`
  via `POST /messages/{id}/singleValueExtendedProperties`. The `fetch_emails`
  query includes this property in `$expand`, so **already-marked emails are
  filtered out** on the next poll. This is the primary de-dup mechanism (the
  category-based approach was replaced by this MAPI marker).

Dedup is therefore **provider-side** (MAPI marker) with a **DB backstop**
(unique `Order.email_message_id`, see §7).

---

## 4. Classification (AI-only)

File: `rfq/ai_classifier.py`

```python
class AiEmailClassifier:
    def __init__(self, client=None): ...        # injectable anthropic.Anthropic
    def classify(self, email: EmailMessage) -> EmailClassification
```

- Uses the Anthropic Messages API with `model` from
  `settings.ANTHROPIC_MODEL` (default `claude-sonnet-4-6`),
  `max_tokens=10`, `temperature=0`.
- Prompt input is `subject + body` truncated to **5000 chars**.
- Response is expected to be a bare token; it is stripped/upper-cased and
  mapped: `RFQ → 'rfq'`, `PURCHASE_ORDER → 'po'`, `QUOTATION → 'quotation'`,
  anything else → `'other'`.
- If the Anthropic client is missing (`ANTHROPIC_API_KEY` not set) or any
  API/response error occurs, it raises **`ClassificationUnavailable`**.
- **There is no keyword/rule-based classifier anymore.** If you ever need a
  fallback, it does not exist by design — AI is the only classification path.

### What happens when classification fails

In `orchestrator.py`, a `ClassificationUnavailable` is caught and converted
into a **pending `tasks.Task`** so a human reviews the email:

- `_create_classification_failure_task(email, exc)` (`orchestrator.py:141`)
- Title: `"RFQ classification failed — review email"`
- Description embeds the subject, sender email, conversation id, and error.
- **Dedup:** if a `pending` task whose description contains the same
  `conversation_id` already exists, no second task is created.
- The email is **not** marked as processed (so it is retried on the next poll).

---

## 5. Orchestrator pipeline

File: `rfq/orchestrator.py` → `EmailIngestionOrchestrator`

Constructor defaults (all injectable):
```python
EmailIngestionOrchestrator(
    email_provider,                     # required
    data_extractor=OpenAiExtractor(),
    rfq_builder=RfqBuilder(),
    classifier=AiEmailClassifier(),
)
```

### `poll_new_emails(days_back=1) -> Dict`
1. `fetch_emails(limit=50, days_back=1)`.
2. For each email:
   - skip if no `id`;
   - `classify()` → on `ClassificationUnavailable` create failure task and
     `continue`;
   - if `'other'` → log + skip;
   - else `_process_one_email()`; if it returns an `Order`, `processed += 1`
     and `mark_as_processed(msg_id)`.
   - exceptions: `'UNIQUE constraint failed: rfq_rfq.email_message_id'` is
     treated as "already processed by another worker" (logged, not an error);
     anything else is appended to `errors`.
3. Returns `{'success', 'processed', 'errors'}`.

### `_process_one_email(email, classification) -> Optional[Order]`
1. `'other'` → skip.
2. **Bounce detection** — if subject+body contain any of
   `delivery failure / delivery status notification / undelivered / bounce /
   returned / failed / not delivered / delivery failed`, skip (bounces should
   not become orders).
3. For `'quotation'` and `'po'` first try to attach to an **existing** order
   via `_find_order_for_quotation(email)`:
   - match RFQ numbers in subject/body with regex patterns:
     `RFQ-YYYYMMDD-XXXXXXXX`, `RFQ-2026-001` / `RFQ-232-7556`, `RFQ-XXXXXXXX`;
   - fallback: match by `company:` line in body → recent `company_name`
     (≤30 days); then by `email_sender` (≤30 days); then by scanning recent
     orders whose `rfq_number` appears in the subject.
   - if found → run `_handle_quotation` or `_handle_po` and return that order.
4. Otherwise create a new Order via `RfqBuilder.create_from_email(...)` with
   `email_message_id=email.id` and `email_classification=classification`.
   - If `'po'`, immediately set `type='purchase_order'`, `stage='order'`,
     `status='processing'`.
5. Dispatch to the per-classification handler.

### `_handle_rfq_po(email, order)`  — an RFQ (or a PO-as-RFQ)
1. Gather attachment content (`_gather_attachments`, see §5a): PDF/DOCX text is
   extracted and image attachments are kept temporarily.
2. Extract structured data from the **email body + extracted attachment text**
   via `OpenAiExtractor.extract()` (image attachments passed alongside for
   visual inspection).
3. If data → `RfqBuilder.update_from_extraction(order, data)` (fills
   company, description, quantity, specs, delivery date, confidence, and
   creates `OrderItem` rows). If extraction returned `None`, log a warning.
4. If the order has **no supplier**, create a
   supplier-assignment task:
   `TaskService.create_supplier_assignment_task(order)` (pending Task).
5. Business Central (only if `settings.BC_SYNC_ENABLED`):
   `create_quotation_in_bc(order)`; on success `status='processing'`.
6. `stage='inquiry'`.

### §5a Attachment handling (`_gather_attachments`)

`_gather_attachments(email, order)` returns `(attachment_text, images)`:

- Uses `email['attachments']` if already normalized by the provider; otherwise
  falls back to `provider.get_attachments(email['id'])`.
- For each attachment, downloads bytes via
  `provider.download_attachment(...)` and stores them **temporarily** under
  `MEDIA_ROOT/temp_attachments/<order_id>/` (via `AttachmentService`).
- **PDF / DOCX** attachments → text extracted with `rfq/document_parsers.py`
  (`PdfParser` via PyPDF2, `DocxParser` via python-docx). The extracted text
  is appended to the email body before AI extraction.
- **Image** attachments (`png/jpg/jpeg/gif/bmp/webp/tiff`) → kept temporarily
  and returned as image payloads `{'data': bytes, 'media_type': str, ...}` so
  the extractor can send them to the AI as vision content blocks.
- Unsupported types are skipped (only a log line is emitted).

The same attachment flow is applied to `_handle_po` and `_handle_quotation`
(quotation text is extracted with `is_quotation=True`).

### `_handle_po(email, order)`  — customer Purchase Order
1. Extract PO number via regex `PO[-: ]?([A-Z0-9-]+)` from subject+body.
2. Extract structured data from body; `update_from_extraction`.
3. Save `po_number`, set `type='purchase_order'`, `stage='order'`,
   `status='processing'`.
4. If `BC_SYNC_ENABLED` → `convert_quote_to_sales_order(order)` then
   `create_purchase_order_in_bc(order)` (exceptions swallowed).

### `_handle_quotation(email, order)`  — supplier quotation reply
1. `OpenAiExtractor.extract(text, is_quotation=True)`.
2. If no items extracted → warn and return (order unchanged).
3. Match each extracted item against existing `OrderItem`s by `item_code`
   (case-insensitive) or by `item_name` substring. Update `unit_price` /
   `total_price` on matches; create new `OrderItem`s for non-matches.
4. If anything was updated/created → `stage='negotiation'`.
5. `create_quotation_in_bc(order)` (exceptions swallowed).

---

## 6. Extraction (AI-only)

File: `rfq/data_extractors.py` → `OpenAiExtractor`

- Only extractor in the codebase (`KeywordExtractor` was deleted).
- Uses the same Anthropic client pattern as the classifier
  (`settings.ANTHROPIC_MODEL`, `OPENAI_MAX_TOKENS` default 4000,
  `OPENAI_TEMPERATURE` default 0.3).
- Body text is capped at **50,000 chars** in the prompt.
- **Images:** when the orchestrator passes `images=` (list of
  `{'data': bytes, 'media_type': str}`), the request content is built as
  Anthropic **vision content blocks** (base64 image blocks first, then the
  text prompt). Without images the message is sent as plain text (unchanged
  behaviour).
- Prompt requests JSON with fields:
  - `company_name`
  - `description`
  - `delivery_date` (YYYY-MM-DD)
  - `items[]`: `item_number`, `name` (the **actual description**, never header
    text), `part_number`, `quantity` (assume 1 if unspecified), `unit`
    (assume `PC`), `unit_price` (null if absent), `total_price` (null if absent).
- Response handling: strips markdown code fences if present, `json.loads`, then
  coerces into `ExtractedRfqData(**data)`; always sets
  `confidence_score = 0.85`.
- Returns `None` on JSON parse failure or any API error (the caller logs a
  warning and continues — extraction failure does **not** create a task, only
  classification failure does).

`RfqBuilder.update_from_extraction` (`rfq/rfq_builder.py:77`) persists the data
and creates `OrderItem` rows with sensible type coercion (string quantities
parsed, defaults of 1 / `PC`, `unit_price`/`total_price` from AI, `item_name`
from `name`→`description`→`item_name`).

---

## 7. Data model & deduplication

`Order` (`rfq/models.py`, table `rfq_rfq`):
- `email_message_id` — **unique, indexed**; the DB backstop for dedup. The
  orchestrator catches the `UNIQUE constraint failed: rfq_rfq.email_message_id`
  error to skip cross-worker duplicates.
- `email_classification` — the AI classification stored on the order.
- `type` ∈ `rfq | purchase_order`, `stage` ∈ `inquiry | quotation |
  negotiation | order | fulfilled | archived`.
- `supplier` (FK) / `suppliers` (M2M through `OrderSupplierAssignment`) —
  supplier targeting for the supplier-assignment task.
- BC fields: `bc_quote_id`, `bc_sales_order_id`, `bc_sales_order_number`,
  `bc_synced`, `bc_synced_at`.
- Attachments are **not** stored on the model; image attachments are kept
  temporarily under `MEDIA_ROOT/temp_attachments/<order_id>/` during ingestion
  (see §5a).

Dedup summary:
1. **Graph API MAPI marker** (`RFQProcessed`) — prevents re-fetch on the next
   poll.
2. **Unique `email_message_id`** — backstop for concurrent workers/races.

`tasks.Task` (table `tasks_task`) is reused for both the classification-failure
review task (§4) and supplier-assignment tasks (§5 / `TaskService.create_supplier_assignment_task`).

---

## 8. Business Central integration

`rfq/business_central.py`:
- `BusinessCentralClient` — thin client over the Dynamics 365 BC API
  (companies, products, sales quotes, quote lines, purchase orders).
- `build_bc_client_for_user(user)` — builds a client from the user's
  BC/OAuth config; returns `None` if unavailable.
- `create_quotation_in_bc(order)` — creates/updates a BC sales quote
  (`bc_quote_id`, `bc_synced`).
- `convert_quote_to_sales_order(order)` — turns the quote into a sales order.
- `create_purchase_order_in_bc(order)` — creates the purchase order.
- All BC calls inside handlers are wrapped in `try/except: pass` and gated on
  `settings.BC_SYNC_ENABLED` (default True).

---

## 9. Entry points / endpoints

- **Manual email pull** → `POST /api/rfq/monitor/emails/pull/`
  (`rfq/views_email.py` `pull_emails`) runs the pipeline synchronously for the
  requesting user and returns the orchestrator summary.
- **Products sync** → `sync_products_from_bc` (in `rfq/views_email.py`).
- The old `get_rfq_emails` endpoint was removed along with the keyword-based
  path.

---

## 10. Settings (config/settings/base.py)

| Setting | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | env | API key for classifier + extractor |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | model for both AI calls |
| `OPENAI_MAX_TOKENS` | `4000` | max tokens for extraction |
| `OPENAI_TEMPERATURE` | `0.3` | temperature for extraction |
| `BC_SYNC_ENABLED` | `False` | master switch for automated Business Central sync during email ingestion (manual sync via `trigger_business_central_sync` stays available) |

---

## 11. Testing

- `rfq/tests/test_orchestrator.py` covers the orchestrator end-to-end with
  `FakeEmailProvider` / `AttachmentProvider`, `FakeExtractor` /
  `RecordingExtractor`, and a fake `RfqClassifier`, plus `AiEmailClassifier`
  unit tests using a mock Anthropic client.
- `rfq/tests/test_data_extractors.py` covers the extractor's text-only and
  vision (image) content-block handling.
- Run from `backend/`:
  ```
  .\..\venv\Scripts\python.exe -m pytest rfq/tests/test_orchestrator.py -v
  ```
- Known pre-existing failure (unrelated): `test_models.py::TestOrderModel::test_email_message_id_dedup`
  conflicts with the committed unique constraint on `Order.email_message_id`.

---

## 12. Common extension points

- **New email category** → extend `EmailClassification` + the classifier
  prompt mapping + add a `_handle_*` method and register it in the handler
  dict in `_process_one_email`.
- **Re-enable automated BC sync** → set `BC_SYNC_ENABLED=true` (no code change
  needed). Manual sync endpoint stays available regardless.
- **Add a document parser** (e.g. XLSX) → add a parser class to
  `rfq/document_parsers.py` and register it in `_PARSERS`.
- **Change polling scope** → `days_back` in `poll_new_emails` / `process_user_emails`.

---

## 13. File inventory (current)

| File | Role |
|---|---|
| `rfq/orchestrator.py` | Pipeline coordinator + per-type handlers + attachment gathering |
| `rfq/ai_classifier.py` | `AiEmailClassifier`, `ClassificationUnavailable` |
| `rfq/data_extractors.py` | `OpenAiExtractor` (AI JSON extraction, optional vision) |
| `rfq/document_parsers.py` | `PdfParser`, `DocxParser`, `extract_text` |
| `rfq/attachment_service.py` | `AttachmentService` / `LocalFileStorage` (temporary storage) |
| `rfq/interfaces.py` | TypedDicts + Protocols |
| `rfq/rfq_builder.py` | Order creation/persistence from extracted data |
| `rfq/email_ingestion_service.py` | Backward-compat wrapper for a user |
| `rfq/business_central.py` | BC client + quote/sales-order/PO functions |
| `rfq/models.py` | `Order`, `OrderItem`, `OrderSupplierAssignment`, etc. |
| `microsoft_auth/graph_api.py` | `GraphEmailProvider` (fetch + attachments + MAPI processed marker) |
| `tasks/models.py`, `tasks/services.py` | `Task` model, `TaskService` |
| `config/settings/base.py` | Feature-flag settings |
| `rfq/views_email.py` | Manual email pull / product-sync endpoints |
