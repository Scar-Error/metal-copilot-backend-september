# POST /api/auth/login/

Obtain JWT access and refresh tokens.

## Request

```json
{
  "username": "string",
  "password": "string"
}
```

## Response 200

```json
{
  "access": "string (JWT, 30min expiry)",
  "refresh": "string (JWT, 1 day expiry)"
}
```

## Response 401

```json
{
  "detail": "No active account found with the given credentials"
}
```
