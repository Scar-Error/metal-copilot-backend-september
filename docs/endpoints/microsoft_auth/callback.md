# GET /api/microsoft/callback/

Microsoft OAuth2 callback — exchanges `code` for Microsoft Graph tokens and links them to the existing user identified by the `state` parameter. Does not create a new user or issue JWTs.

## Query Parameters

| Param | Description |
|-------|-------------|
| `code` | Authorization code from Microsoft |
| `state` | User ID (set by `microsoft_login`) — used to identify which user to link the Microsoft account to |

## Response 302

On success:
```
{FRONTEND_URL}/auth/callback?status=success&email=<url-encoded-email>
```

On failure:
```
{FRONTEND_URL}/auth/callback?error=<error_code>
```

Error codes: `token_failed`, `user_info_failed`, `no_code`, `no_state`, `invalid_state`
