# POST /api/microsoft/disconnect/

Clear the stored `microsoft_refresh_token` and `microsoft_email` from the user's profile. Django account remains active — only the Microsoft link is severed.

## Headers

```
Authorization: Bearer <access_token>
```

## Response 200

```json
{
  "detail": "Microsoft account disconnected"
}
```
