# file: agent/enhanced_executor_status.py
from pydantic import BaseModel, Field
from typing import Optional, Literal, Union, List, Dict, Any

from agent.enhanced_planner import ExecutionPlan, PlanStep
from agent.execution_result import ExecutionResult

# --- 基类 ---
class BaseExecutorStatus(BaseModel):
    """所有 EnhancedExecutor 状态更新的基类。"""
    type: Literal["executor_status"] = "executor_status"
    message: str = Field(description="向用户展示的友好信息。")

# --- 通用状态 ---
class ExecutorStatusUpdate(BaseExecutorStatus):
    """通用的状态/进度更新。"""
    subtype: Literal["status_update"] = "status_update"

# --- 任务级别状态 ---
class TaskExecutionStart(BaseExecutorStatus):
    """表示增强任务开始。"""
    subtype: Literal["task_start"] = "task_start"
    task_description: str

class TaskExecutionEnd(BaseExecutorStatus):
    """表示增强任务结束。"""
    subtype: Literal["task_end"] = "task_end"
    success: bool
    final_result: Optional[ExecutionResult] = None
    execution_time: float
    stats: Dict[str, Any]

class FinalScriptExtracted(BaseExecutorStatus):
    """在任务成功后，专门用于提取最终脚本的状态。"""
    subtype: Literal["final_script"] = "final_script"
    script: str

# --- 计划级别状态 ---
class PlanGenerationStart(BaseExecutorStatus):
    """表示开始生成执行计划。"""
    subtype: Literal["plan_start"] = "plan_start"

class PlanGenerationEnd(BaseExecutorStatus):
    """表示计划生成结束。"""
    subtype: Literal["plan_end"] = "plan_end"
    plan: ExecutionPlan

class RecoveryPlanStart(BaseExecutorStatus):
    """表示为失败的步骤开始生成恢复计划。"""
    subtype: Literal["recovery_start"] = "recovery_start"
    failed_step: PlanStep

class RecoveryPlanEnd(BaseExecutorStatus):
    """表示恢复计划生成结束。"""
    subtype: Literal["recovery_end"] = "recovery_end"
    new_plan: ExecutionPlan

# --- 步骤级别状态 ---
class StepExecutionStart(BaseExecutorStatus):
    """表示开始执行一个步骤。"""
    subtype: Literal["step_start"] = "step_start"
    step: PlanStep

class StepExecutionEnd(BaseExecutorStatus):
    """表示一个步骤执行结束。"""
    subtype: Literal["step_end"] = "step_end"
    step: PlanStep
    result: ExecutionResult
    execution_time: float

# --- 错误状态 ---
class ExecutorError(BaseExecutorStatus):
    """表示执行过程中发生可处理或不可处理的错误。"""
    subtype: Literal["error"] = "error"
    step: Optional[PlanStep] = None # 哪个步骤出错了
    error_details: str

# --- 联合类型 ---
from typing import Annotated

AnyExecutorStatus = Annotated[
    Union[
        ExecutorStatusUpdate,
        TaskExecutionStart,
        TaskExecutionEnd,
        FinalScriptExtracted,
        PlanGenerationStart,
        PlanGenerationEnd,
        RecoveryPlanStart,
        RecoveryPlanEnd,
        StepExecutionStart,
        StepExecutionEnd,
        ExecutorError,
    ],
    Field(discriminator="subtype"),
]