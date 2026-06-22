# POST /api/rfqs/{id}/send_to_supplier/

Send the RFQ as an email to the supplier. Uses a Django template (`email/rfq_to_supplier.html`) with auto‑escaped output.

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
  "message": "RFQ email sent to supplier@example.com"
}
```

## Response 400

```json
{
  "error": "No supplier email configured"
}
```
