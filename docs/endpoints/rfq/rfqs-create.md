# POST /api/rfqs/

Create a new RFQ manually.

## Headers

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

## Request Body

```json
{
  "email_subject": "Quote request for widgets",
  "email_sender": "supplier@example.com",
  "email_received_at": "2025-06-01T10:30:00Z",
  "email_body": "",
  "source": "manual",
  "rfq_number": "RFQ-2025-0042",
  "company_name": "Acme Corp",
  "status": "pending",
  "priority": "medium",
  "items_description": "",
  "quantity": null,
  "specifications": "",
  "delivery_date": null,
  "budget": null,
  "notes": ""
}
```

## Response 201

Returns the created RFQ (same schema as list detail). The `items` and `attachments` arrays will be empty initially.

## Validation

- `rfq_number` must be unique.
- `quantity` must be ≥ 0 (if provided).
- `status` must be one of `pending`, `processing`, `completed`, `rejected`.
- `priority` must be one of `low`, `medium`, `high`, `urgent`.
- `source` defaults to `email`; use `manual` for manual creation.
- `unit_price` ≥ `total_price` when both provided.
