# Authentication and Profile Routes

Authentication is fully local. Passwords are hashed with scrypt in SQLite, short-lived JWT access tokens authorize API requests, and rotating refresh tokens are stored in SQLite and sent as HTTP-only cookies.

## Public Routes

- `POST /api/auth/register` accepts `name`, `email`, and `password`.
- `POST /api/auth/login` accepts `email` and `password`.
- `POST /api/auth/refresh` rotates the refresh cookie and returns a new access token.
- `POST /api/auth/logout` revokes the refresh token and clears its cookie.

Registration and login return the public user profile and an `access_token`. Protected requests send `Authorization: Bearer <access_token>`.

## Profile Routes

- `GET /api/auth/me` returns the current profile.
- `GET /api/auth/profile` returns the current profile.
- `PATCH /api/auth/profile` updates the display name, theme, or password. A password change requires `current_password`.
- `POST /api/auth/avatar` stores a JPEG, PNG, WebP, or GIF under `data/avatars/`.
- `DELETE /api/auth/me` removes the account and its related local records.

There is no Google OAuth, external authentication provider, email verification, or email password-reset workflow.
