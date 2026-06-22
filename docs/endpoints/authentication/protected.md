# GET /api/auth/protected/

Test endpoint requiring authentication. Returns current user info.

## Headers

```
Authorization: Bearer <access_token>
```

## Response 200

```json
{
  "id": 1,
  "username": "string",
  "email": "string"
}
```

## POST /api/auth/refresh/

Same token‑pair schema as login.

## Request

```json
{
  "refresh": "string (refresh token)"
}
```

## Response 200

```json
{
  "access": "string (new JWT)",
  "refresh": "string (new refresh token)"
}
```
