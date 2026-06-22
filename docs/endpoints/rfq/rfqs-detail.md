# GET /api/rfqs/{id}/

Retrieve a single RFQ by ID.

## Headers

```
Authorization: Bearer <access_token>
```

## Response 200

Same schema as list result (single object with nested `items` and `attachments`).

## Response 404

```json
{
  "detail": "Not found"
}
```
