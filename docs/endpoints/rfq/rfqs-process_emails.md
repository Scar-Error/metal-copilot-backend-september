# POST /api/rfqs/process_emails/

Trigger the email ingestion pipeline synchronously (no Celery). This is called by `trigger_email_monitoring` in production.

## Headers

```
Authorization: Bearer <access_token>
```

## Request Body

*(empty)*

## Response 200

```json
{
  "success": true,
  "message": "Emails processed successfully",
  "new_rfqs": 3,
  "skipped": 1
}
```
