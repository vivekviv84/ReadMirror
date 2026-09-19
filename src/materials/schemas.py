from pydantic import BaseModel, Field

class URLInput(BaseModel):
    url: str


class RenameMaterialRequest(BaseModel):
    title: str


class BulkDeleteRequest(BaseModel):
    material_ids: list[str]


class TopicRequest(BaseModel):
    topic: str


class TextMaterialRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=20, max_length=500_000)


class SearchRequest(BaseModel):
    q: str
