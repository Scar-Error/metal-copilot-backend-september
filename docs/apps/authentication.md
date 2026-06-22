# Authentication

Simple JWT‑based authentication.

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/auth/login/` | Obtain JWT access + refresh tokens |
| POST | `/api/auth/refresh/` | Refresh an expired access token |
| GET | `/api/auth/protected/` | Test endpoint — returns current user info |

## Details

- [`POST /api/auth/login/`](../endpoints/authentication/login.md)
- [`POST /api/auth/refresh/`](../endpoints/authentication/protected.md) *(uses same token‑pair response schema)*
- [`GET /api/auth/protected/`](../endpoints/authentication/protected.md)
