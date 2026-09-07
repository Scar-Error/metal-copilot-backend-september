# RFQ

Core RFQ management — CRUD, ingestion, analytics, Business Central sync, monitoring.

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/rfqs/` | List RFQs (paginated) |
| POST | `/api/rfqs/` | Create RFQ manually |
| GET | `/api/rfqs/{id}/` | RFQ detail |
| PUT | `/api/rfqs/{id}/` | Full update |
| PATCH | `/api/rfqs/{id}/` | Partial update |
| DELETE | `/api/rfqs/{id}/` | Delete RFQ |
| GET | `/api/rfqs/analytics/` | Analytics data (daily) |
| GET | `/api/rfqs/dashboard_stats/` | Aggregated dashboard stats |
| POST | `/api/rfqs/{id}/review/` | Review / approve an RFQ |
| POST | `/api/rfqs/process_emails/` | Trigger email ingestion pipeline |
| GET | `/api/rfqs/{rfq_id}/items/` | List items for an RFQ |
| POST | `/api/rfqs/{rfq_id}/items/` | Create item |
| GET | `/api/rfqs/{rfq_id}/items/{id}/` | Item detail |
| PUT | `/api/rfqs/{rfq_id}/items/{id}/` | Full update item |
| PATCH | `/api/rfqs/{rfq_id}/items/{id}/` | Partial update item |
| DELETE | `/api/rfqs/{rfq_id}/items/{id}/` | Delete item |
| GET | `/api/rfqs/{rfq_id}/attachments/` | List attachments |
| POST | `/api/rfqs/{rfq_id}/attachments/` | Upload attachment |
| GET | `/api/rfqs/{rfq_id}/attachments/{id}/` | Attachment detail |
| PUT | `/api/rfqs/{rfq_id}/attachments/{id}/` | Full update attachment |
| PATCH | `/api/rfqs/{rfq_id}/attachments/{id}/` | Partial update attachment |
| DELETE | `/api/rfqs/{rfq_id}/attachments/{id}/` | Delete attachment |
| POST | `/api/rfq/monitor/emails/pull/` | Manually pull Outlook emails into email threads |
| POST | `/api/rfq/monitor/sync-products/` | Sync products from Business Central |

## Details

- [`GET/POST /api/rfqs/`](../endpoints/rfq/rfqs-list.md)
- [`POST /api/rfqs/` (detail)](../endpoints/rfq/rfqs-create.md)
- [`GET /api/rfqs/{id}/`](../endpoints/rfq/rfqs-detail.md)
- [`PUT/PATCH /api/rfqs/{id}/`](../endpoints/rfq/rfqs-update.md)
- [`DELETE /api/rfqs/{id}/`](../endpoints/rfq/rfqs-delete.md)
- [`GET /api/rfqs/analytics/`](../endpoints/rfq/rfqs-analytics.md)
- [`GET /api/rfqs/dashboard_stats/`](../endpoints/rfq/rfqs-dashboard_stats.md)
- [`POST /api/rfqs/{id}/review/`](../endpoints/rfq/rfqs-review.md)
- [`POST /api/rfqs/process_emails/`](../endpoints/rfq/rfqs-process_emails.md)
- [`CRUD /api/rfqs/{rfq_id}/items/`](../endpoints/rfq/items-list.md) — list, create, detail, update, delete
- [`CRUD /api/rfqs/{rfq_id}/attachments/`](../endpoints/rfq/attachments-list.md) — list, create, detail, update, delete
- [`Monitor endpoints`](../endpoints/rfq/monitor-trigger_email_monitoring.md)
