# GET /api/microsoft/login/

Initiate Microsoft OAuth2 consent flow. Returns the Microsoft Entra ID authorization URL which the frontend opens in a popup.

## Headers

```
Authorization: Bearer <access_token>
```

## Response 200

```json
{
  "success": true,
  "auth_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?client_id=..."
}
```

The frontend opens `auth_url` in a popup window. After consent, Microsoft redirects to the callback endpoint which links the account to the currently authenticated user.

## Response 401

```json
{
  "detail": "Authentication credentials were not provided."
}
```
