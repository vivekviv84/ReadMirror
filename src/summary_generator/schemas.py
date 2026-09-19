from pydantic import BaseModel, Field
from typing import Optional

class SummarizeRequest(BaseModel):
    material_id: str


class SummarizeResponse(BaseModel):
    summary: str
    time_taken: float
    glossary: list[dict] = Field(default_factory=list)


class WordInfoRequest(BaseModel):
    word: str


class WordInfoResponse(BaseModel):
    word: str
    normalized_word: str
    meaning: str
    synonym: str
    language: str = ""
    cached: bool


class DetailedSummaryRequest(BaseModel):
    start_page: int = Field(default=1, ge=1)
    page_count: int = Field(default=5, ge=1, le=5)
