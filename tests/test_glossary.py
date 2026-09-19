from unittest.mock import patch

import pytest
from httpx import AsyncClient

from src.store import save_summary
from src.summary_generator.summary import normalize_glossary_word
from tests.conftest import register_user


def test_filler_and_invalid_selections_are_rejected_without_ai():
    assert normalize_glossary_word("the") is None
    assert normalize_glossary_word("and") is None
    assert normalize_glossary_word("two words") is None
    assert normalize_glossary_word("42") is None
    assert normalize_glossary_word("photosynthesis") == "photosynthesis"


@pytest.mark.anyio
async def test_word_information_is_generated_once_then_served_from_sqlite(client: AsyncClient):
    session = await register_user(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    topic = await client.post("/api/materials/topic", headers=headers, json={"topic": "Plant Biology"})
    assert topic.status_code == 200, topic.text
    material_id = topic.json()["material_id"]
    save_summary(
        material_id=material_id,
        user_id=session["user"]["id"],
        summary="Photosynthesis converts light energy into chemical energy.",
        time_taken=0.1,
        model_name="test",
    )

    filler = await client.post(
        f"/api/materials/{material_id}/word-info",
        headers=headers,
        json={"word": "the"},
    )
    assert filler.status_code == 400

    generated = {
        "word": "Photosynthesis",
        "normalized_word": "photosynthesis",
        "meaning": "The process plants use to convert light into chemical energy.",
        "synonym": "assimilation",
        "language": "English",
    }
    with patch("src.summary_generator.routes.define_word", return_value=generated) as define_mock:
        first = await client.post(
            f"/api/materials/{material_id}/word-info",
            headers=headers,
            json={"word": "Photosynthesis"},
        )
        second = await client.post(
            f"/api/materials/{material_id}/word-info",
            headers=headers,
            json={"word": "photosynthesis"},
        )

    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    assert second.status_code == 200, second.text
    assert second.json()["cached"] is True
    assert second.json()["synonym"] == "assimilation"
    define_mock.assert_called_once()
