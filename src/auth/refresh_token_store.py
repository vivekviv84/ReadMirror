"""SQLite-backed refresh-token storage."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.auth.constants import REFRESH_TOKEN_EXPIRE_DAYS
from src.database import get_database


def save_refresh_token(user_id: str, token_hash: str, email: str = "") -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    with get_database().connection() as conn:
        conn.execute(
            """INSERT INTO refresh_tokens(token_hash, user_id, email, expires_at, revoked)
               VALUES (?, ?, ?, ?, 0)
               ON CONFLICT(token_hash) DO UPDATE SET user_id=excluded.user_id,
               email=excluded.email, expires_at=excluded.expires_at, revoked=0""",
            (token_hash, user_id, email, expires_at),
        )
        conn.commit()


def get_refresh_token(token_hash: str) -> Optional[dict]:
    with get_database().connection() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    return dict(row) if row else None


def revoke_refresh_token(token_hash: str) -> None:
    with get_database().connection() as conn:
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?", (token_hash,))
        conn.commit()


def revoke_all_user_tokens(user_id: str) -> None:
    with get_database().connection() as conn:
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()


def is_token_valid(row: dict) -> bool:
    if not row or row.get("revoked") in (True, "1", 1):
        return False
    try:
        expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < expires_at
    except (KeyError, TypeError, ValueError):
        return False
