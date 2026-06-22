# RFQ Management API

Request for Quotation (RFQ) management backend — Django REST Framework + Celery.

## Authentication

All endpoints except `POST /api/auth/login/` require an **access token** obtained from login.

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "...", "password": "..."}'
```

Response:
```json
{
  "access": "<access_token>",
  "refresh": "<refresh_token>"
}
```

Attach to subsequent requests:
```
Authorization: Bearer <access_token>
```

Refresh when expired:
```bash
curl -X POST http://localhost:8000/api/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh_token>"}'
```

Access tokens expire in **30 minutes**; refresh tokens expire in **1 day**.

### Microsoft OAuth Alternative

- `GET /api/microsoft/login/` — redirects to Microsoft Entra ID consent screen.
- `GET /api/microsoft/callback/` — finishes OAuth, redirects to frontend with `#access=...&refresh=...`.
- `POST /api/microsoft/refresh/` — exchange Microsoft refresh token for new Django tokens.
- `POST /api/microsoft/disconnect/` — clear Microsoft tokens, keep Django session.

---

## Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | Deleted (no body) |
| 400 | Validation error |
| 401 | Unauthenticated |
| 403 | Forbidden |
| 404 | Not found |
| 500 | Server error |

---

## Apps

| App | Description | Endpoints |
|-----|-------------|-----------|
| [`authentication`](apps/authentication.md) | JWT login, refresh, protected test | 3 |
| [`microsoft_auth`](apps/microsoft_auth.md) | Microsoft Entra ID OAuth2 flow | 4 |
| [`rfq`](apps/rfq.md) | Core RFQ CRUD, items, attachments, analytics, monitoring, BC sync | 28 |

---

## Data Model

Core models (see `rfq/models.py`):

| Model | Purpose |
|-------|---------|
| `RFQ` | Request for Quotation — email metadata, extracted fields, status, BC sync |
| `RFQItem` | Line items within an RFQ (product, quantity, price) |
| `RFQAttachment` | Uploaded files linked to an RFQ |
| `RFQAnalytics` | Daily aggregation of processing metrics |
| `Product` | Item master synced from Business Central |

---

## Monitoring Tasks

All monitoring endpoints return a Celery `AsyncResult` with this shape:

```json
{
  "task_id": "uuid",
  "status": "SUCCESS|FAILURE|PENDING|STARTED",
  "result": { ... },
  "error": null
}
```

Refer to endpoint‑specific `docs/endpoints/rfq/monitor-*.md` for `result` schemas.
