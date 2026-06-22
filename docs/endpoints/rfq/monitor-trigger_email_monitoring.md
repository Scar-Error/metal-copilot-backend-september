# Monitor Endpoints

All monitor endpoints trigger or inspect Celery async tasks.

## POST /api/rfqs/monitor/trigger_email_monitoring/

Fetch new emails from Microsoft Graph and create RFQs.

**Response 202:**
```json
{
  "task_id": "uuid",
  "status": "PENDING"
}
```

## POST /api/rfqs/monitor/trigger_ai_processing/

Run AI extraction on unprocessed RFQs.

**Response 202** — same task schema.

## POST /api/rfqs/monitor/trigger_bc_sync/

Sync RFQs to Business Central as sales quotes + purchase orders.

**Response 202** — same task schema.

## POST /api/rfqs/monitor/sync_products/

Sync product master from Business Central into the local `Product` model.

**Response 202:**
```json
{
  "task_id": "uuid",
  "status": "PENDING"
}
```

## POST /api/rfqs/monitor/get_microsoft_emails/

Fetch emails from Microsoft Graph. Same as `trigger_email_monitoring` but returns the raw Celery task.

**Response 202:**
```json
{
  "task_id": "uuid",
  "status": "PENDING"
}
```

## GET /api/rfqs/monitor/get_rfq_emails/

Trigger an email fetch and return the task ID for polling.

**Response 200:**
```json
{
  "task_id": "uuid"
}
```

## GET /api/rfqs/monitor/get_task_status/{task_id}/

Poll the status of any Celery task.

**Response 200:**
```json
{
  "task_id": "uuid",
  "status": "SUCCESS|FAILURE|PENDING|STARTED",
  "result": { },
  "error": null
}
```

When `status` is `SUCCESS`, `result` contains the task's return value. When `FAILURE`, `error` contains the traceback.
