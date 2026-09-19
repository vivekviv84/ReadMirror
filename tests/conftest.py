import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


TEST_DIR = Path(tempfile.mkdtemp(prefix="study-buddy-tests-"))
os.environ["SQLITE_PATH"] = str(TEST_DIR / "test.db")
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-local-auth-only"
os.environ["ENVIRONMENT"] = "development"

from src.auth.rate_limiter import _cooldowns, _store
from src.database import get_database
from src.main import app


pytest_plugins = ["anyio"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_local_state():
    _store.clear()
    _cooldowns.clear()
    database = get_database()
    with database.connection() as connection:
        for table in (
            "refresh_tokens", "chat_messages", "chat_sessions", "quiz_attempts",
            "quizzes", "page_summaries", "difficult_concepts", "material_glossary", "summaries", "material_embeddings", "material_chunks",
            "materials", "profiles",
        ):
            connection.execute(f'DELETE FROM "{table}"')
        connection.commit()
    yield
    _store.clear()
    _cooldowns.clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def register_user(client: AsyncClient, email: str = "test@example.com", password: str = "password123") -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"name": "Test User", "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()
