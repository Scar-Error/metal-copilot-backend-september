# DELETE /api/rfqs/{id}/

Delete an RFQ and its related items and attachments (cascade).

## Headers

```
Authorization: Bearer <access_token>
```

## Response 204

No body.

## Response 404

```json
{
  "detail": "Not found"
}
```
