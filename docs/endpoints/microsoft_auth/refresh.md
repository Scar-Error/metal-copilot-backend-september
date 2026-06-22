# POST /api/microsoft/refresh/

Refresh an expired Microsoft Graph API access token using the stored Microsoft refresh token. This does not issue Django JWTs — it only refreshes the Microsoft token used for Graph API calls (email reading/sending).

## Headers

```
Authorization: Bearer <access_token>
```

## Request Body

*(empty — the stored Microsoft refresh token is looked up from the user's DB record)*

## Response 200

```json
{
  "success": true,
  "access_token": "string (new Microsoft Graph token)",
  "expires_at": "2025-01-01T00:00:00+00:00"
}
```

## Response 401

```json
{
  "success": false,
  "error": "Not authenticated"
}
```

## Response 404

```json
{
  "success": false,
  "error": "No Microsoft token"
}
```
