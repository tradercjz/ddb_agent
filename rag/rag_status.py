from pydantic import BaseModel, Field
from typing import Optional, Literal, Union

# --- 基础状态类 ---

class BaseRagStatus(BaseModel):
    """所有 RAG 状态更新的基类。"""
    type: Literal["rag_status"] = "rag_status"
    message: str = Field(description="向用户展示的友好信息。")

# --- 具体的状态子类 ---

class RagStart(BaseRagStatus):
    """表示RAG流程开始。"""
    subtype: Literal["start"] = "start"

class RagIndexLoaded(BaseRagStatus):
    """表示索引已加载。"""
    subtype: Literal["index_loaded"] = "index_loaded"
    total_items: int = Field(description="加载的索引项总数。")

class RagSelectionStart(BaseRagStatus):
    """表示候选选择阶段开始。"""
    subtype: Literal["selection_start"] = "selection_start"
    strategy: str = Field(description="使用的选择策略（如 'llm', 'keyword'）。")

class RagSelectionProgress(BaseRagStatus):
    """表示候选选择正在进行中（尤其适用于并行LLM筛选）。"""
    subtype: Literal["selection_progress"] = "selection_progress"
    processed_count: int
    total_count: int
    found_count: int

class RagSelectionEnd(BaseRagStatus):
    """表示候选选择阶段结束。"""
    subtype: Literal["selection_end"] = "selection_end"
    candidate_count: int = Field(description="此阶段后找到的候选文档数量。")

class RagRerankStart(BaseRagStatus):
    """表示LLM重排阶段开始。"""
    subtype: Literal["rerank_start"] = "rerank_start"
    candidate_count: int = Field(description="进入重排阶段的候选文档数量。")

class RagRerankEnd(BaseRagStatus):
    """表示LLM重排阶段结束。"""
    subtype: Literal["rerank_end"] = "rerank_end"
    final_count: int = Field(description="重排后最终选择的文档数量。")

class RagContentRetrievalStart(BaseRagStatus):
    """表示开始获取最终文档的内容。"""
    subtype: Literal["content_retrieval"] = "content_retrieval"
    document_count: int

class RagEnd(BaseRagStatus):
    """表示整个RAG流程成功结束。"""
    subtype: Literal["end"] = "end"
    final_document_count: int

class RagError(BaseRagStatus):
    """表示RAG流程中发生错误。"""
    subtype: Literal["error"] = "error"
    step: str = Field(description="发生错误的步骤（如 'selection', 'rerank'）。")
    error_details: Optional[str] = None

from typing import Annotated

AnyRagStatus = Annotated[
    Union[
        RagStart,
        RagIndexLoaded,
        RagSelectionStart,
        RagSelectionProgress,
        RagSelectionEnd,
        RagRerankStart,
        RagRerankEnd,
        RagContentRetrievalStart,
        RagEnd,
        RagError,
    ],
    Field(discriminator="subtype"),
]