# GET /api/rfqs/dashboard_stats/

Aggregated statistics for the dashboard.

## Headers

```
Authorization: Bearer <access_token>
```

## Response 200

```json
{
  "total_rfqs": 42,
  "pending_count": 10,
  "processing_count": 5,
  "completed_count": 25,
  "rejected_count": 2,
  "urgent_count": 3,
  "high_priority_count": 8,
  "avg_confidence": 0.85,
  "recent_rfqs": [
    {
      "id": 42,
      "rfq_number": "RFQ-2025-0042",
      "company_name": "Acme Corp",
      "status": "pending",
      "priority": "urgent",
      "created_at": "2025-06-21T10:00:00Z"
    }
  ]
}
```

`recent_rfqs` contains the latest 10 RFQs.
