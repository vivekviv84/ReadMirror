import json
import re
import unicodedata
from loguru import logger
from langchain_core.messages import HumanMessage
from src.rag.rag import get_summary_llm, get_summary_fallback_llm, _agentic_gather_web_content
from .constants import (
    SUMMARIZER_PROMPT_TEMPLATE,
    WEB_SUMMARIZER_PROMPT_TEMPLATE,
    MAX_INPUT_CHARS,
    WIKI_TOP_K_RESULTS,
    WIKI_DOC_CONTENT_CHARS_MAX,
)


FILLER_WORDS = {
    "a", "about", "after", "again", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "between", "both", "but",
    "by", "can", "could", "did", "do", "does", "doing", "each", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "may", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "of", "on", "once", "only", "or",
    "other", "our", "ours", "ourselves", "out", "over", "same", "she", "should", "so", "some",
    "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very",
    "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "will", "with", "would", "you", "your", "yours", "yourself", "yourselves",
}


def normalize_glossary_word(value: str) -> str | None:
    word = unicodedata.normalize("NFKC", value or "").strip()
    word = re.sub(r"^[^\w]+|[^\w]+$", "", word, flags=re.UNICODE)
    if not word or len(word) < 3 or len(word) > 64 or re.search(r"\s", word):
        return None
    if not any(character.isalpha() for character in word):
        return None
    normalized = word.casefold()
    if normalized in FILLER_WORDS:
        return None
    return normalized


def _json_from_model(content) -> dict | list:
    text = content if isinstance(content, str) else str(content)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start_candidates = [position for position in (text.find("["), text.find("{")) if position >= 0]
    if start_candidates:
        text = text[min(start_candidates):]
    end = max(text.rfind("]"), text.rfind("}"))
    if end >= 0:
        text = text[:end + 1]
    return json.loads(text)


def _validated_term(term: dict) -> dict | None:
    word = str(term.get("word", "")).strip()
    normalized = normalize_glossary_word(word)
    meaning = str(term.get("meaning", "")).strip()
    synonym = str(term.get("synonym", "")).strip().split()[0] if term.get("synonym") else ""
    synonym = synonym.strip(".,;:!?()[]{}\"'")
    if not normalized or not meaning or not synonym or normalize_glossary_word(synonym) is None:
        return None
    return {
        "word": word,
        "normalized_word": normalized,
        "meaning": meaning[:500],
        "synonym": synonym[:64],
        "language": str(term.get("language", "")).strip()[:32],
    }


def extract_difficult_words(summary: str) -> list[dict]:
    """Extract a compact, useful glossary from a completed summary."""
    prompt = """Analyze the educational summary below and return a JSON array of difficult,
technical, academic, or domain-specific SINGLE words that a student may need explained.
For each term return: word, meaning, synonym, language.

Rules:
- Include 8 to 25 genuinely useful difficult words when available.
- Exclude articles, pronouns, conjunctions, prepositions, auxiliary verbs, generic verbs,
  common adjectives, headings, names, numbers, abbreviations without educational value,
  and all other filler/common words.
- Each `word` must be one lexical word occurring in the summary, never a phrase.
- `meaning` must be a concise explanation in the same language as the summary.
- `synonym` must contain exactly one word in that language.
- Return only valid JSON. Return [] when there are no suitable terms.

SUMMARY:
""" + summary[:30000]
    response = get_summary_fallback_llm().invoke([HumanMessage(content=prompt)])
    parsed = _json_from_model(response.content)
    items = parsed.get("terms", []) if isinstance(parsed, dict) else parsed
    unique: dict[str, dict] = {}
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        term = _validated_term(raw)
        if term:
            unique.setdefault(term["normalized_word"], term)
    return list(unique.values())[:25]


def define_word(word: str, summary_context: str) -> dict:
    normalized = normalize_glossary_word(word)
    if not normalized:
        raise ValueError("Select one meaningful word, not a filler or common word.")
    prompt = f"""Define the selected word using its context in the educational summary.
Return only one JSON object with: word, meaning, synonym, language.
The meaning must be concise and in the summary's language. The synonym must be exactly one word.
Do not invent a definition if the selection is a filler/common word.

SELECTED WORD: {word}
SUMMARY CONTEXT:
{summary_context[:20000]}
"""
    response = get_summary_fallback_llm().invoke([HumanMessage(content=prompt)])
    parsed = _json_from_model(response.content)
    term = _validated_term(parsed if isinstance(parsed, dict) else {})
    if not term:
        raise ValueError("No useful definition was found for that word.")
    term["word"] = word.strip()
    term["normalized_word"] = normalized
    return term


def generate_difficult_concepts(text: str) -> list[dict]:
    prompt = """Identify the genuinely difficult concepts in this educational document.
Return only valid JSON as an array of objects with exactly these fields:
title, explanation, example.

Rules:
- Include 4 to 12 technical, abstract, or easily misunderstood concepts when available.
- Do not include filler words, ordinary vocabulary, headings, names, or trivial facts.
- Explain each concept clearly for a learner in 2-4 sentences.
- Give one concrete, useful example for every concept.
- Use the same language as the document.
- Return [] if there are no difficult concepts.

DOCUMENT:
""" + _truncate_text(text, 40000)
    response = get_summary_fallback_llm().invoke([HumanMessage(content=prompt)])
    parsed = _json_from_model(response.content)
    items = parsed.get("concepts", []) if isinstance(parsed, dict) else parsed
    concepts = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        explanation = str(item.get("explanation", "")).strip()
        example = str(item.get("example", "")).strip()
        if title and explanation and example:
            concepts.append({
                "title": title[:160],
                "explanation": explanation[:1500],
                "example": example[:1000],
            })
    return concepts[:12]


def generate_page_summaries(pages: list[dict]) -> list[dict]:
    page_text = "\n\n".join(
        f"--- PAGE {page['page_number']} ---\n{page['content'][:12000]}"
        for page in pages
    )
    prompt = """Create a detailed, self-contained summary for each supplied page.
Return only valid JSON as an array of objects with exactly: page_number, summary.
Preserve every supplied page number. Summarize each page separately; never merge pages.
For blank or nearly blank pages, state that there is no substantial readable content.
Use clear paragraphs and bullet points where useful, in the document's language.

PAGES:
""" + page_text
    response = get_summary_fallback_llm().invoke([HumanMessage(content=prompt)])
    parsed = _json_from_model(response.content)
    items = parsed.get("pages", []) if isinstance(parsed, dict) else parsed
    allowed = {int(page["page_number"]) for page in pages}
    summaries = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item.get("page_number"))
        except (TypeError, ValueError):
            continue
        summary = clean_summary(str(item.get("summary", "")).strip())
        if page_number in allowed and summary:
            summaries.append({"page_number": page_number, "summary": summary[:6000]})
    return summaries


def summarizer_prompt():
    return SUMMARIZER_PROMPT_TEMPLATE



def clean_summary(text: str) -> str:
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Remove markdown table separator lines (e.g. |---|---|)
        if re.match(r'^[\s\|]*[-]{2,}[\s\|]*$', stripped):
            continue
        # If it's a table row, just keep it but maybe clean it up a bit
        if re.match(r'^\|.*\|$', stripped):
            parts = [p.strip() for p in stripped.split('|')]
            parts = [p for p in parts if p]
            line = ' | '.join(parts)
        # Note: We NO LONGER strip bold (**) here because the frontend uses it for styling
        cleaned.append(line)
    return '\n'.join(cleaned)


def _truncate_text(text: str, max_chars: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    first_len = int(max_chars * 0.6)
    last_len = max_chars - first_len
    first_part = text[:first_len]
    last_part = text[-last_len:]
    logger.info(f"Text truncated from {len(text)} to {max_chars} chars")
    return f"{first_part}\n\n...[content truncated]...\n\n{last_part}"


def summarizer(text: str) -> str:
    logger.info(f"Summarizer started for text of length {len(text)}")
    text = _truncate_text(text)
    prompt = summarizer_prompt()

    try:
        llm = get_summary_llm()
        chain = prompt | llm
        response = chain.invoke({"input": text})
        return clean_summary(response.content)
    except Exception as e:
        logger.warning(f"Primary summary model (gemini-3.5-flash-lite) failed: {e}. Falling back to gemini-3.1-flash-lite.")
        try:
            fallback_llm = get_summary_fallback_llm()
            chain = prompt | fallback_llm
            response = chain.invoke({"input": text})
            return clean_summary(response.content)
        except Exception as fallback_err:
            logger.error(f"Fallback summary generation failed: {fallback_err}", exc_info=True)
            raise fallback_err


def fetch_web_content(topic: str) -> str:
    """
    Fetch web content for *topic* using the agentic tool-selection engine.

    The router LLM decides which combination of Wikipedia, DuckDuckGo, and
    ArXiv will produce the richest educational content for this topic, then
    executes the selected tools in parallel and returns the combined text.

    The returned text can be:
    - Chunked and stored in the DB for future reuse.
    - Passed directly to an LLM prompt as context.
    """
    logger.info(f"fetch_web_content (agentic) started for topic: {topic}")
    combined, has_wiki, has_ddg, has_arxiv = _agentic_gather_web_content(
        query=topic,
        is_topic=True,
        existing_doc_context="",
        subject_title="",
    )
    if not combined or not combined.strip():
        logger.warning(f"No web content found for topic: {topic}. Returning placeholder.")
        return f"No web content found for: {topic}"
    logger.info(
        f"fetch_web_content done for '{topic}': "
        f"wiki={has_wiki} ddg={has_ddg} arxiv={has_arxiv} chars={len(combined)}"
    )
    return combined


def web_summarizer(topic: str, raw_content: str | None = None) -> str:
    """
    Generate an LLM summary for *topic*.

    If *raw_content* is provided (pre-fetched web text) it is used directly,
    skipping the Wiki/DDG network calls.  Otherwise fetch_web_content() is
    called internally so this function stays usable standalone.
    """
    logger.info(f"Web summarizer started for topic: {topic}")

    combined = raw_content if raw_content is not None else fetch_web_content(topic)
    combined = _truncate_text(combined)

    try:
        llm = get_summary_llm()
        chain = WEB_SUMMARIZER_PROMPT_TEMPLATE | llm
        response = chain.invoke({"topic": topic, "input": combined})
        return clean_summary(response.content)
    except Exception as e:
        logger.warning(f"Primary web summarizer model (gemini-3.5-flash-lite) failed: {e}. Falling back to gemini-3.1-flash-lite.")
        try:
            fallback_llm = get_summary_fallback_llm()
            chain = WEB_SUMMARIZER_PROMPT_TEMPLATE | fallback_llm
            response = chain.invoke({"topic": topic, "input": combined})
            return clean_summary(response.content)
        except Exception as fallback_err:
            logger.error(f"Fallback web summarizer failed: {fallback_err}", exc_info=True)
            raise fallback_err
