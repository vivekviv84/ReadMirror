import PyPDF2
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import UnstructuredURLLoader


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove NULL bytes (\x00 / \u0000) which PostgreSQL text format cannot accept
    return text.replace("\x00", "").replace("\u0000", "")


def pages_from_pdf(pdf_file) -> list[str]:
    reader = PyPDF2.PdfReader(pdf_file)
    return [_clean_text(page.extract_text() or "").strip() for page in reader.pages]


def text_from_pdf(pdf_file) -> str:
    return "\n\n".join(page for page in pages_from_pdf(pdf_file) if page)


def paginate_text(text: str, page_size: int = 3500) -> list[str]:
    """Split pasted/web text into stable virtual pages without cutting paragraphs when possible."""
    cleaned = _clean_text(text).strip()
    if not cleaned:
        return []
    pages: list[str] = []
    current = ""
    for paragraph in cleaned.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > page_size:
            pages.append(current)
            current = ""
        while len(paragraph) > page_size:
            split_at = paragraph.rfind(" ", 0, page_size)
            split_at = split_at if split_at > page_size // 2 else page_size
            if current:
                pages.append(current)
                current = ""
            pages.append(paragraph[:split_at].strip())
            paragraph = paragraph[split_at:].strip()
        current = f"{current}\n\n{paragraph}".strip()
    if current:
        pages.append(current)
    return pages


def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 150):
    cleaned = _clean_text(text)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    chunks = splitter.split_text(cleaned)
    return [_clean_text(c) for c in chunks if _clean_text(c).strip()]


def scrap_website(url: str) -> str:
    loader = UnstructuredURLLoader(urls=[url], ssl_verify=True)
    data = loader.load()
    raw = data[0].page_content if data else ""
    return _clean_text(raw)
