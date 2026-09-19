from io import BytesIO

import pytest
from httpx import AsyncClient

from src.auth.constants import MAX_FILE_SIZE_BYTES
from tests.conftest import register_user


@pytest.mark.anyio
async def test_avatar_is_saved_locally(client: AsyncClient):
    session = await register_user(client)
    response = await client.post(
        "/api/auth/upload-avatar",
        headers={"Authorization": f"Bearer {session['access_token']}"},
        files={"file": ("avatar.png", BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["avatar_url"].startswith("http://test/avatars/")


@pytest.mark.anyio
async def test_avatar_rejects_invalid_type_and_size(client: AsyncClient):
    session = await register_user(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    wrong_type = await client.post(
        "/api/auth/upload-avatar",
        headers=headers,
        files={"file": ("notes.pdf", BytesIO(b"%PDF"), "application/pdf")},
    )
    assert wrong_type.status_code == 400

    too_large = await client.post(
        "/api/auth/upload-avatar",
        headers=headers,
        files={"file": ("large.png", BytesIO(b"x" * (MAX_FILE_SIZE_BYTES + 1)), "image/png")},
    )
    assert too_large.status_code == 400


@pytest.mark.anyio
async def test_password_change_requires_current_password(client: AsyncClient):
    session = await register_user(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    missing = await client.patch("/api/auth/profile", headers=headers, json={"password": "newpassword123"})
    assert missing.status_code == 400

    wrong = await client.patch(
        "/api/auth/profile",
        headers=headers,
        json={"current_password": "incorrect", "password": "newpassword123"},
    )
    assert wrong.status_code == 400

    changed = await client.patch(
        "/api/auth/profile",
        headers=headers,
        json={"current_password": "password123", "password": "newpassword123"},
    )
    assert changed.status_code == 200
    login = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "newpassword123"})
    assert login.status_code == 200
