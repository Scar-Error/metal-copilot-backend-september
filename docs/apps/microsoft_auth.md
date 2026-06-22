# Microsoft Authentication

OAuth2 integration via Microsoft Entra ID (Azure AD) for email access (reading and sending). This is **not** an authentication method — it links a Microsoft account to an existing user for Graph API access.

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/microsoft/login/` | Get Microsoft OAuth consent URL |
| GET | `/api/microsoft/callback/` | OAuth callback — links Microsoft account to existing user |
| POST | `/api/microsoft/refresh/` | Refresh the Microsoft Graph access token |
| POST | `/api/microsoft/disconnect/` | Clear stored Microsoft tokens |

## Details

- [`GET /api/microsoft/login/`](../endpoints/microsoft_auth/login.md)
- [`GET /api/microsoft/callback/`](../endpoints/microsoft_auth/callback.md)
- [`POST /api/microsoft/refresh/`](../endpoints/microsoft_auth/refresh.md)
- [`POST /api/microsoft/disconnect/`](../endpoints/microsoft_auth/disconnect.md)
