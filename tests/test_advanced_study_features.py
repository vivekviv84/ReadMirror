from unittest.mock import patch

import pytest
from httpx import AsyncClient

from src.store import create_material, save_chunks, update_material_status
from tests.conftest import register_user


def _material_with_pages(user_id: str, title: str, page_count: int) -> str:
    material = create_material(user_id=user_id, source_type="text", title=title)
    chunks = [f"Technical content for page {page}. " * 20 for page in range(1, page_count + 1)]
    save_chunks(material["id"], chunks, list(range(1, page_count + 1)))
    update_material_status(material["id"], "ready")
    return material["id"]


@pytest.mark.anyio
async def test_difficult_concepts_are_generated_once_then_cached(client: AsyncClient):
    session = await register_user(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    material_id = _material_with_pages(session["user"]["id"], "Concept Cache", 2)
    concepts = [{
        "title": "Backpropagation",
        "explanation": "A learning method that propagates output error backward through a network.",
        "example": "A classifier adjusts earlier layer weights after predicting the wrong label.",
    }]

    with patch("src.summary_generator.routes.generate_difficult_concepts", return_value=concepts) as generator:
        first = await client.post(f"/api/materials/{material_id}/difficult-concepts", headers=headers)
        second = await client.post(f"/api/materials/{material_id}/difficult-concepts", headers=headers)
        stored = await client.get(f"/api/materials/{material_id}/difficult-concepts", headers=headers)

    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert stored.json()["concepts"] == concepts
    generator.assert_called_once()


@pytest.mark.anyio
async def test_detailed_summary_generates_at_most_five_pages_and_caches_batches(client: AsyncClient):
    session = await register_user(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    material_id = _material_with_pages(session["user"]["id"], "Seven Pages", 7)

    def summarize(pages):
        return [
            {"page_number": page["page_number"], "summary": f"Summary for page {page['page_number']}"}
            for page in pages
        ]

    with patch("src.summary_generator.routes.generate_page_summaries", side_effect=summarize) as generator:
        first = await client.post(
            f"/api/materials/{material_id}/detailed-summary",
            headers=headers,
            json={"start_page": 1, "page_count": 5},
        )
        second = await client.post(
            f"/api/materials/{material_id}/detailed-summary",
            headers=headers,
            json={"start_page": 6, "page_count": 5},
        )
        cached = await client.post(
            f"/api/materials/{material_id}/detailed-summary",
            headers=headers,
            json={"start_page": 1, "page_count": 5},
        )

    assert [page["page_number"] for page in first.json()["pages"]] == [1, 2, 3, 4, 5]
    assert first.json()["next_start"] == 6
    assert first.json()["has_more"] is True
    assert [page["page_number"] for page in second.json()["pages"]] == [6, 7]
    assert second.json()["has_more"] is False
    assert cached.json()["cached"] is True
    assert generator.call_count == 2
