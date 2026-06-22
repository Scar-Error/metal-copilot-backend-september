# POST /api/rfqs/{id}/review/

Review and approve/reject an RFQ. Reviews can only be made by authenticated staff users. The endpoint enforces valid status transitions:

- `pending` → `processing`
- `processing` → `completed` or `rejected`
- `rejected` → `pending` (re‑open)
- `completed` → no further transitions allowed

## Headers

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

## Request Body

```json
{
  "status": "completed",
  "notes": "Approved — pricing confirmed with supplier"
}
```

## Response 200

Returns the updated RFQ (full object schema).

## Response 400

```json
{
  "error": "Cannot transition from 'completed' to 'pending'"
}
```
