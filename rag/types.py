# file: ddb_agent/rag/types.py

import pydantic
from typing import List, Dict, Any, Optional

class Symbol(pydantic.BaseModel):
    """
    Represents a code symbol (e.g., class, function).
    """
    name: str = pydantic.Field(description="The name of the symbol.")
    type: str = pydantic.Field(description="The type of the symbol (e.g., 'class', 'function').")

class FileIndex(pydantic.BaseModel):
    """
    Represents the indexed metadata for a single source file.
    """
    module_name: str = pydantic.Field(description="The path to the source file.")
    file_summary: str = pydantic.Field(description="A brief summary of the file's purpose and functionality.")
    symbols: List[Symbol] = pydantic.Field(description="A list of key symbols defined in the file.")
    # Optional: You can add other metadata if needed, e.g., dependencies
    dependencies: Optional[List[str]] = pydantic.Field(default_factory=list, description="List of modules this file depends on.")
    is_aggregated: bool = pydantic.Field(default=False, description="Indicates if this index is an aggregation of multiple chunks.")
    chunk_count: Optional[int] = pydantic.Field(None, description="Number of chunks if aggregated.")
    tokens: Optional[int] = pydantic.Field(None, description="file tokens.")

class ProjectIndex(pydantic.BaseModel):
    """
    Represents the entire project's index, which is a collection of FileIndex objects.
    """
    files: List[FileIndex] = pydantic.Field(description="A list of all indexed files in the project.")