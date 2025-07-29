# file: agent/enhanced_planner_status.py
from pydantic import BaseModel, Field
from typing import Optional, Literal, Union, List, Dict, Any

# --- 基类 ---
class BasePlannerStatus(BaseModel):
    """所有 EnhancedPlanner 状态更新的基类。"""
    type: Literal["planner_status"] = "planner_status"
    message: str = Field(description="向用户展示的友好信息。")

# --- 具体状态子类 ---
class RAGContextStart(BasePlannerStatus):
    """表示开始进行 RAG 上下文检索。"""
    subtype: Literal["rag_start"] = "rag_start"

class RAGContextEnd(BasePlannerStatus):
    """表示 RAG 上下文检索结束。"""
    subtype: Literal["rag_end"] = "rag_end"
    context: str = Field(description="检索到的上下文内容。")

class ComplexityAnalysisStart(BasePlannerStatus):
    """表示开始分析任务复杂度。"""
    subtype: Literal["complexity_start"] = "complexity_start"

class ComplexityAnalysisEnd(BasePlannerStatus):
    """表示任务复杂度分析结束。"""
    subtype: Literal["complexity_end"] = "complexity_end"
    complexity: str = Field(description="分析出的复杂度级别 (e.g., 'SIMPLE', 'MEDIUM')。")

class InitialPlanGenerationStart(BasePlannerStatus):
    """表示开始生成初始计划。"""
    subtype: Literal["initial_plan_start"] = "initial_plan_start"

class LLMPlanResponse(BasePlannerStatus):
    """表示从LLM收到了原始的计划响应（JSON字符串）。"""
    subtype: Literal["llm_plan_response"] = "llm_plan_response"
    raw_response: str = Field(description="LLM返回的原始JSON字符串。")

class PlannerError(BasePlannerStatus):
    """表示规划过程中发生错误。"""
    subtype: Literal["error"] = "error"
    error_details: str

# --- 联合类型 ---
from typing import Annotated

AnyPlannerStatus = Annotated[
    Union[
        RAGContextStart,
        RAGContextEnd,
        ComplexityAnalysisStart,
        ComplexityAnalysisEnd,
        InitialPlanGenerationStart,
        LLMPlanResponse,
        PlannerError,
    ],
    Field(discriminator="subtype"),
]