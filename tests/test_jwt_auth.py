import time

import jwt
import pytest
from httpx import AsyncClient

from src.auth.constants import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_COOKIE_NAME
from src.auth.jwt_utils import create_access_token, create_refresh_token, decode_access_token, hash_token
from tests.conftest import register_user


def test_jwt_creation_tamper_detection_and_refresh_hashing():
    before = time.time()
    token = create_access_token("user-id", "test@example.com")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-id"
    assert abs(payload["exp"] - (before + ACCESS_TOKEN_EXPIRE_MINUTES * 60)) < 5
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token[:-4] + "xxxx")
    refresh = create_refresh_token()
    assert len(hash_token(refresh)) == 64
    assert refresh != create_refresh_token()


@pytest.mark.anyio
async def test_complete_local_auth_lifecycle(client: AsyncClient):
    registration = await register_user(client)
    assert registration["user"]["email"] == "test@example.com"
    assert REFRESH_COOKIE_NAME in client.cookies

    duplicate = await client.post(
        "/api/auth/register",
        json={"name": "Duplicate", "email": "TEST@example.com", "password": "password123"},
    )
    assert duplicate.status_code == 409

    bad_login = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong"})
    assert bad_login.status_code == 401

    login = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
    assert login.status_code == 200
    access_token = login.json()["access_token"]

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    assert me.json()["user"]["name"] == "Test User"

    refreshed = await client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert "access_token" in refreshed.json()

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    blocked = await client.post("/api/auth/refresh")
    assert blocked.status_code == 401


@pytest.mark.anyio
async def test_protected_route_rejects_missing_or_tampered_token(client: AsyncClient):
    assert (await client.get("/api/auth/me")).status_code == 401
    token = create_access_token("missing-user", "missing@example.com")
    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token[:-4]}xxxx"})
    assert response.status_code == 401
