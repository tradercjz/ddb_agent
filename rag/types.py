# file: ddb_agent/rag/types.py

import pydantic
from typing import Annotated, List, Literal, Optional, Union

class BaseIndexModel(pydantic.BaseModel):
    """
    Marker base class for all index model types (e.g., CodeIndex, TextChunkIndex).
    """
    pass


class Symbol(pydantic.BaseModel):
    """
    Represents a code symbol (e.g., class, function).
    """
    name: str = pydantic.Field(description="The name of the symbol.")
    type: str = pydantic.Field(description="The type of the symbol (e.g., 'class', 'function').")

class CodeIndex(BaseIndexModel):
    """
    Represents the indexed metadata for a single source file.
    """
    model_type: Literal["code"] = "code"
    file_path: str = pydantic.Field(description="The path to the source file.")
    file_summary: str = pydantic.Field(description="A brief summary of the file's purpose and functionality.")
    symbols: List[Symbol] = pydantic.Field(description="A list of key symbols defined in the file.")
    # Optional: You can add other metadata if needed, e.g., dependencies
    dependencies: Optional[List[str]] = pydantic.Field(default_factory=list, description="List of modules this file depends on.")
    is_aggregated: bool = pydantic.Field(default=False, description="Indicates if this index is an aggregation of multiple chunks.")
    chunk_count: Optional[int] = pydantic.Field(None, description="Number of chunks if aggregated.")
    tokens: Optional[int] = pydantic.Field(None, description="file tokens.")
    file_hash: Optional[str] = pydantic.Field(None, description="The MD5 hash of the file content at the time of indexing.")

class TextChunkIndex(BaseIndexModel):
    """
    Represents the indexed metadata for a single chunk of text.
    """
    model_type: Literal["text_chunk"] = "text_chunk"
    
    file_path: str = pydantic.Field(description="The path to the source file containing the chunk.")
    chunk_id: str = pydantic.Field(description="A unique identifier for the chunk (e.g., 'doc_name-chunk__0').")
    source_document: str = pydantic.Field(description="The path or name of the source document.")
    
    start_line: int = pydantic.Field(description="The starting line number of the chunk in the original document.")
    end_line: int = pydantic.Field(description="The ending line number of the chunk in the original document.")
    
    summary: str = pydantic.Field(description="A concise summary of the chunk's content.")
    keywords: List[str] = pydantic.Field(description="A list of keywords representing the chunk's topics.")
    hypothetical_question: Optional[str] = pydantic.Field(None, description="A representative question this chunk can answer.")
    tokens: Optional[int] = pydantic.Field(None, description="file tokens.")
    file_hash: Optional[str] = pydantic.Field(None, description="The MD5 hash of the file content at the time of indexing.")


class ProjectIndex(BaseIndexModel):
    """
    Represents the entire project's index, containing a collection of file/chunk indexes.
    """
    # 这是关键！
    # 我们告诉 Pydantic，files 是一个列表，列表中的每个元素
    # 都属于 AnyIndexModel (即 TextChunkIndex 或 CodeIndex)。
    # Pydantic 应该查看每个元素的 'model_type' 字段来决定使用哪个具体模型。
    files: List[Annotated[Union[TextChunkIndex, CodeIndex], pydantic.Field(discriminator='model_type')]]
    
    # 你还可以添加其他元数据
    project_name: Optional[str] = None
    version: str = "1.0"