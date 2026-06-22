# CRUD /api/rfqs/{rfq_id}/attachments/

Nested CRUD for file attachments linked to an RFQ.

## GET /api/rfqs/{rfq_id}/attachments/

```json
[
  {
    "id": 1,
    "rfq": 1,
    "filename": "quote.pdf",
    "file_path": "/uploads/quote.pdf",
    "file_size": 102400,
    "file_type": "PDF",
    "mime_type": "application/pdf",
    "uploaded_at": "2025-06-01T10:30:00Z"
  }
]
```

## POST /api/rfqs/{rfq_id}/attachments/

```json
{
  "filename": "spec.pdf",
  "file_path": "/uploads/spec.pdf",
  "file_size": 204800,
  "file_type": "PDF",
  "mime_type": "application/pdf"
}
```

Response **201** with the created attachment object.

## GET /api/rfqs/{rfq_id}/attachments/{id}/

Retrieve a single attachment.

## PUT /api/rfqs/{rfq_id}/attachments/{id}/

Full update.

## PATCH /api/rfqs/{rfq_id}/attachments/{id}/

Partial update.

## DELETE /api/rfqs/{rfq_id}/attachments/{id}/

Response **204**.
