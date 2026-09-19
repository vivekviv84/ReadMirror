"""Authentication dependencies for locally-issued JWTs."""

from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

from src.auth.jwt_utils import decode_access_token


def _extract_token(request: Request) -> Optional[str]:
    token = request.headers.get("x-auth-token")
    if token:
        return token
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return None


async def get_current_user_id(request: Request) -> str:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing subject")
        return str(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token")


async def get_current_user(request: Request) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(token)
        return {"id": str(payload["sub"]), "email": payload.get("email", "")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token")
