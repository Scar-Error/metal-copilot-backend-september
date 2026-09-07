# POST /api/rfqs/process_emails/

Trigger the email ingestion pipeline synchronously.

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
