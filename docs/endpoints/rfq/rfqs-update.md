# PUT /api/rfqs/{id}/

Full update. All required fields must be present.

# PATCH /api/rfqs/{id}/

Partial update. Only supplied fields are changed.

## Headers

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

## Request Body (PUT — full)

```json
{
  "email_subject": "Updated quote request",
  "email_sender": "new@example.com",
  "email_received_at": "2025-06-02T10:30:00Z",
  "email_body": "",
  "source": "email",
  "rfq_number": "RFQ-2025-0042",
  "company_name": "Acme Corp Updated",
  "status": "processing",
  "priority": "high",
  "items_description": "Updated description",
  "quantity": 200,
  "specifications": "Updated specs",
  "delivery_date": "2025-08-01",
  "budget": "10000.00",
  "notes": "Updated notes"
}
```

## Request Body (PATCH — partial)

```json
{
  "status": "completed",
  "priority": "high"
}
```

## Response 200

Returns the updated RFQ object.

> **Note**: `reviewed_by`, `bc_*`, `ai_*`, and `processing_*` fields are managed by the system and should generally not be manually set via PUT/PATCH.
