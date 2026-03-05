from typing import List, Optional, Union, Literal
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Query text")
    mode: Literal["local", "global", "hybrid", "naive"] = Field(
        default="hybrid", description="Query mode"
    )


class MultimodalQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Query text")
    mode: Literal["local", "global", "hybrid", "naive"] = Field(
        default="hybrid", description="Query mode"
    )
    multimodal_content: List[dict] = Field(
        default_factory=list, description="Multimodal content items"
    )


class QueryResponse(BaseModel):
    result: Union[str, dict]  # Can be either a string or structured JSON response


# Excel Processing Models
class ExcelProcessingRequest(BaseModel):
    max_rows: Optional[int] = None
    sheet_name: Union[str, int, List[str]] = 0
    convert_to_text: bool = True
    include_summary: bool = True
    chunk_size: int = 100
    doc_id: Optional[str] = None


class ExcelProcessingResponse(BaseModel):
    success: bool
    doc_id: str
    total_rows: int
    columns: List[str]
    chunks_created: int
    metadata: Optional[dict] = None


# Generic file processing response
class FileProcessingResponse(BaseModel):
    success: bool
    message: str
    file_path: Optional[str] = None
    metadata: Optional[dict] = None
