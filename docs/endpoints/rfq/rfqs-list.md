# GET /api/rfqs/

List all RFQs (paginated).

## Headers

```
Authorization: Bearer <access_token>
```

## Response 200

```json
{
  "count": 42,
  "next": "http://localhost:8000/api/rfqs/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "email_subject": "Quote request for widgets",
      "email_sender": "supplier@example.com",
      "email_received_at": "2025-06-01T10:30:00Z",
      "email_body": "We need 100 units of ...",
      "source": "email",
      "email_message_id": "<abc123@mail.example.com>",
      "rfq_number": "RFQ-2025-0001",
      "company_name": "Acme Corp",
      "supplier_email": "supplier@example.com",
      "status": "pending",
      "priority": "medium",
      "items_description": "Widgets and doohickeys",
      "quantity": 100,
      "specifications": "ISO 9001 compliant",
      "delivery_date": "2025-07-01",
      "budget": "5000.00",
      "attachment_filename": "quote.pdf",
      "attachment_path": "/uploads/quote.pdf",
      "attachment_size": 102400,
      "ai_processed": false,
      "ai_confidence_score": null,
      "processing_errors": "",
      "supplier_email_sent": false,
      "supplier_email_sent_at": null,
      "supplier_email_error": "",
      "bc_quote_id": "",
      "bc_synced": false,
      "bc_synced_at": null,
      "reviewed_by": null,
      "reviewed_at": null,
      "notes": "",
      "created_at": "2025-06-01T10:30:01Z",
      "updated_at": "2025-06-01T10:30:01Z",
      "items": [
        {
          "id": 1,
          "item_name": "Widget",
          "item_code": "WGT-100",
          "description": "Standard widget",
          "quantity": 100,
          "unit": "pcs",
          "unit_price": "50.00",
          "total_price": "5000.00",
          "extraction_confidence": 0.95,
          "created_at": "2025-06-01T10:30:02Z",
          "updated_at": "2025-06-01T10:30:02Z"
        }
      ],
      "attachments": [
        {
          "id": 1,
          "filename": "quote.pdf",
          "file_path": "/uploads/quote.pdf",
          "file_size": 102400,
          "file_type": "PDF",
          "mime_type": "application/pdf",
          "uploaded_at": "2025-06-01T10:30:00Z"
        }
      ]
    }
  ]
}
```
