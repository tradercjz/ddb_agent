# file: ddb_agent/rag/retrieval_result.py
from pydantic import BaseModel
from typing import List, Optional

class RetrievalResult(BaseModel):
    """
    A unified data structure for returning retrieval results from any index manager.
    """
    source: str # The path to the original source file or document
    content: str # The retrieved content (can be a full file or a chunk)
    score: float # The relevance score of this result
    metadata: Optional[dict] = None # For extra info, like line numbers