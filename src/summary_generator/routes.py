import asyncio
import time
from loguru import logger
from fastapi import APIRouter, HTTPException, Depends

from src.summary_generator.summary import (
    define_word,
    extract_difficult_words,
    generate_difficult_concepts,
    generate_page_summaries,
    fetch_web_content,
    normalize_glossary_word,
    summarizer,
    web_summarizer,
)
from src.materials.text_utils import chunk_text
from src.rag.rag import store_embeddings_async
from src.store import (
    get_material, get_chunks, save_chunks, save_summary,
    get_summary as get_stored_summary, update_material_status,
    get_glossary, get_glossary_word, save_glossary_terms,
    get_material_pages, get_difficult_concepts, save_difficult_concepts,
    get_page_summaries, save_page_summaries,
    atomic_check_and_increment_daily_limit, decrement_daily_usage, ADMIN_EMAILS,
)
from src.dependencies import get_current_user_id, get_current_user
from src.config import settings
from .schemas import SummarizeRequest, SummarizeResponse, WordInfoRequest, WordInfoResponse, DetailedSummaryRequest
from .constants import MAX_COMBINED_TEXT_LEN

router = APIRouter(prefix="/api/materials", tags=["Summarizer"])


def _owned_material(material_id: str, user_id: str) -> dict:
    material = get_material(material_id)
    if not material:
        raise HTTPException(404, "Material not found")
    if material.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    return material


@router.post("/summarize", response_model=SummarizeResponse)
async def generate_summary(
    body: SummarizeRequest,
    user_id: str = Depends(get_current_user_id),
    current_user=Depends(get_current_user),
):
    # Atomically reserve a daily request slot before starting expensive generation.
    user_email = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", None)
    is_admin = bool(user_email and user_email in ADMIN_EMAILS)
    if not atomic_check_and_increment_daily_limit(user_id, email=user_email, limit=20):
        raise HTTPException(429, "Daily limit of 20 requests reached. Come back tomorrow!")

    mat = get_material(body.material_id)
    if not mat:
        if not is_admin:
            decrement_daily_usage(user_id)
        raise HTTPException(404, "Material not found")
    if mat.get("user_id") != user_id:
        if not is_admin:
            decrement_daily_usage(user_id)
        raise HTTPException(403, "Access denied")

    try:
        start = time.time()
        loop = asyncio.get_event_loop()

        if mat.get("source_type") == "topic":
            topic_title = mat.get("title", "topic")

            # ── Lazy cache check ───────────────────────────────────────────────
            # Check whether we already have stored chunks for this topic.
            # If yes: use them directly (no web fetching).
            # If no: fetch web content, chunk + embed it, then summarize.
            existing_chunks = await loop.run_in_executor(None, get_chunks, body.material_id)

            if existing_chunks:
                # Fast path — use cached chunks
                logger.info(
                    f"Topic '{topic_title}' has {len(existing_chunks)} cached chunks — "
                    "skipping web fetch for summarization."
                )
                combined = "\n".join(c["content"] for c in existing_chunks)
                if len(combined) > MAX_COMBINED_TEXT_LEN:
                    half = MAX_COMBINED_TEXT_LEN // 2
                    combined = combined[:half] + combined[-half:]
                summary = await loop.run_in_executor(None, summarizer, combined)

            else:
                # First-time path — fetch, cache, then summarize
                logger.info(
                    f"Topic '{topic_title}' has no cached chunks — fetching web content."
                )
                raw_content = await loop.run_in_executor(None, fetch_web_content, topic_title)

                # Chunk + store + embed (mirrors the URL pipeline)
                chunks_texts = await loop.run_in_executor(
                    None, lambda: chunk_text(raw_content, chunk_size=600, chunk_overlap=100)
                )
                if chunks_texts:
                    chunk_ids = await loop.run_in_executor(
                        None, save_chunks, body.material_id, chunks_texts
                    )
                    await store_embeddings_async(body.material_id, chunk_ids, chunks_texts)
                    logger.info(
                        f"Cached {len(chunks_texts)} chunks for topic '{topic_title}'."
                    )

                # Generate summary from the raw fetched content
                summary = await loop.run_in_executor(
                    None, web_summarizer, topic_title, raw_content
                )

        else:
            chunks_list = get_chunks(body.material_id)
            if not chunks_list:
                raise HTTPException(400, "No text chunks found in this material")
            combined = "\n".join(c["content"] for c in chunks_list)
            if len(combined) > MAX_COMBINED_TEXT_LEN:
                half_len = MAX_COMBINED_TEXT_LEN // 2
                combined = combined[:half_len] + combined[-half_len:]
            summary = await loop.run_in_executor(None, summarizer, combined)

        elapsed = time.time() - start

        save_summary(
            material_id=body.material_id,
            user_id=user_id,
            summary=summary,
            time_taken=elapsed,
            model_name=settings.model_name,
        )

        glossary = []
        try:
            terms = await loop.run_in_executor(None, extract_difficult_words, summary)
            glossary = await loop.run_in_executor(
                None,
                save_glossary_terms,
                body.material_id,
                terms,
                "summary",
            )
            logger.info(f"Stored {len(glossary)} glossary terms for material {body.material_id}")
        except Exception as glossary_error:
            logger.warning(f"Summary saved, but glossary extraction failed: {glossary_error}")

        return SummarizeResponse(summary=summary, time_taken=elapsed, glossary=glossary)
    except HTTPException:
        # Refund on any HTTP exception raised inside the try block (e.g. 400).
        if not is_admin:
            decrement_daily_usage(user_id)
        raise
    except Exception as e:
        if not is_admin:
            decrement_daily_usage(user_id)
        raise HTTPException(500, f"Summarization failed: {e}")


@router.get("/{material_id}/summary")
async def get_material_summary(
    material_id: str,
    user_id: str = Depends(get_current_user_id),
    current_user=Depends(get_current_user),
):
    mat = get_material(material_id)
    if not mat or mat.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    summary = get_stored_summary(material_id)
    if not summary:
        logger.info("no summary found")
        return {"summary": None, "time_taken": 0, "glossary": []}
    return {
        "summary": summary["summary"],
        "time_taken": summary.get("time_taken", 0),
        "glossary": get_glossary(material_id),
    }


@router.get("/{material_id}/glossary")
async def get_material_glossary(
    material_id: str,
    user_id: str = Depends(get_current_user_id),
):
    mat = get_material(material_id)
    if not mat or mat.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    return {"glossary": get_glossary(material_id)}


@router.post("/{material_id}/word-info", response_model=WordInfoResponse)
async def get_word_information(
    material_id: str,
    body: WordInfoRequest,
    user_id: str = Depends(get_current_user_id),
):
    mat = get_material(material_id)
    if not mat or mat.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    normalized = normalize_glossary_word(body.word)
    if not normalized:
        raise HTTPException(400, "Select one meaningful word, not a filler or common word.")

    cached = get_glossary_word(material_id, normalized)
    if cached:
        return WordInfoResponse(**cached, cached=True)

    summary = get_stored_summary(material_id)
    if not summary:
        raise HTTPException(409, "Generate the summary before looking up words.")

    try:
        term = await asyncio.to_thread(define_word, body.word, summary["summary"])
        saved = await asyncio.to_thread(
            save_glossary_terms,
            material_id,
            [term],
            "selection",
        )
        record = saved[0] if saved else term
        return WordInfoResponse(**record, cached=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error(f"Word lookup failed for material {material_id}: {exc}")
        raise HTTPException(502, "Could not retrieve word information right now.")


@router.get("/{material_id}/difficult-concepts")
async def get_material_difficult_concepts(
    material_id: str,
    user_id: str = Depends(get_current_user_id),
):
    _owned_material(material_id, user_id)
    cached = get_difficult_concepts(material_id)
    return {"concepts": cached.get("concepts", []) if cached else [], "generated": bool(cached)}


@router.post("/{material_id}/difficult-concepts")
async def create_material_difficult_concepts(
    material_id: str,
    user_id: str = Depends(get_current_user_id),
):
    _owned_material(material_id, user_id)
    cached = get_difficult_concepts(material_id)
    if cached:
        return {"concepts": cached.get("concepts", []), "cached": True}
    chunks = get_chunks(material_id)
    if not chunks:
        raise HTTPException(409, "This material is still being processed.")
    combined = "\n".join(chunk["content"] for chunk in chunks)
    try:
        concepts = await asyncio.to_thread(generate_difficult_concepts, combined)
        save_difficult_concepts(material_id, user_id, concepts, settings.model_name)
        return {"concepts": concepts, "cached": False}
    except Exception as exc:
        logger.error(f"Difficult concept generation failed for {material_id}: {exc}")
        raise HTTPException(502, "Could not generate difficult concepts right now.")


@router.get("/{material_id}/detailed-summary")
async def get_material_detailed_summary(
    material_id: str,
    user_id: str = Depends(get_current_user_id),
):
    _owned_material(material_id, user_id)
    source_pages = get_material_pages(material_id)
    saved = get_page_summaries(material_id)
    return {
        "pages": saved,
        "total_pages": len(source_pages),
        "next_start": (max((item["page_number"] for item in saved), default=0) + 1),
        "has_more": len(saved) < len(source_pages),
    }


@router.post("/{material_id}/detailed-summary")
async def create_material_detailed_summary(
    material_id: str,
    body: DetailedSummaryRequest,
    user_id: str = Depends(get_current_user_id),
):
    _owned_material(material_id, user_id)
    source_pages = get_material_pages(material_id)
    if not source_pages:
        raise HTTPException(409, "This material is still being processed.")
    by_number = {int(page["page_number"]): page for page in source_pages}
    requested_numbers = sorted(by_number)[body.start_page - 1:body.start_page - 1 + body.page_count]
    if not requested_numbers:
        return {"pages": [], "total_pages": len(source_pages), "next_start": None, "has_more": False, "cached": True}
    existing = {int(item["page_number"]): item for item in get_page_summaries(material_id)}
    missing = [by_number[number] for number in requested_numbers if number not in existing]
    if missing:
        try:
            generated = await asyncio.to_thread(generate_page_summaries, missing)
            generated_numbers = {int(item["page_number"]) for item in generated}
            for page in missing:
                if int(page["page_number"]) not in generated_numbers:
                    generated.append({"page_number": page["page_number"], "summary": "No detailed summary could be generated for this page."})
            save_page_summaries(material_id, user_id, generated, settings.model_name)
            existing = {int(item["page_number"]): item for item in get_page_summaries(material_id)}
        except Exception as exc:
            logger.error(f"Detailed summary generation failed for {material_id}: {exc}")
            raise HTTPException(502, "Could not generate the detailed summary right now.")
    pages = [existing[number] for number in requested_numbers if number in existing]
    last_index = body.start_page - 1 + len(requested_numbers)
    return {
        "pages": pages,
        "total_pages": len(source_pages),
        "next_start": last_index + 1 if last_index < len(source_pages) else None,
        "has_more": last_index < len(source_pages),
        "cached": not missing,
    }
