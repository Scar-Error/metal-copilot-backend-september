# CRUD /api/rfqs/{rfq_id}/items/

Nested CRUD for line items within an RFQ.

## GET /api/rfqs/{rfq_id}/items/

List items for an RFQ.

```json
[
  {
    "id": 1,
    "rfq": 1,
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
]
```

## POST /api/rfqs/{rfq_id}/items/

```json
{
  "item_name": "Widget",
  "item_code": "WGT-100",
  "description": "Standard widget",
  "quantity": 100,
  "unit": "pcs",
  "unit_price": "50.00",
  "total_price": "5000.00"
}
```

Response **201** with the created item object.

## GET /api/rfqs/{rfq_id}/items/{id}/

Retrieve a single item.

## PUT /api/rfqs/{rfq_id}/items/{id}/

Full update (all required fields).

## PATCH /api/rfqs/{rfq_id}/items/{id}/

Partial update.

## DELETE /api/rfqs/{rfq_id}/items/{id}/

Response **204**.

### Validation

- `quantity` ≥ 0.
- When both `unit_price` and `total_price` are provided, `unit_price` ≤ `total_price`.
