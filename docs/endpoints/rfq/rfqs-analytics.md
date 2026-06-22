# GET /api/rfqs/analytics/

Retrieve daily analytics records.

## Headers

```
Authorization: Bearer <access_token>
```

## Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `date_from` | string (ISO date) | Filter start date |
| `date_to` | string (ISO date) | Filter end date |

## Response 200

```json
[
  {
    "id": 1,
    "date": "2025-06-01",
    "total_rfqs_received": 15,
    "total_rfqs_processed": 12,
    "total_rfqs_completed": 8,
    "total_rfqs_rejected": 2,
    "avg_processing_time_hours": 4.5,
    "avg_ai_confidence_score": 0.87,
    "unique_companies": 10,
    "created_at": "2025-06-01T23:59:59Z",
    "updated_at": "2025-06-01T23:59:59Z"
  }
]
```
