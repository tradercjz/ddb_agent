from pydantic import BaseModel, Field
from typing import Optional, Literal, Union, List, Dict, Any
from agent.execution_result import ExecutionResult
from typing import Annotated

# --- 基类 ---
class BaseTaskStatus(BaseModel):
    """所有任务状态更新的基类。"""
    type: Literal["task_status"] = "task_status"
    message: str = Field(description="向用户展示的友好信息。")

# --- 通用状态子类 ---

class TaskStart(BaseTaskStatus):
    """表示任务开始。"""
    subtype: Literal["start"] = "start"
    task_description: str

class TaskEnd(BaseTaskStatus):
    """表示任务结束。"""
    subtype: Literal["end"] = "end"
    success: bool
    final_message: str

class TaskError(BaseTaskStatus):
    """表示任务中发生严重错误。"""
    subtype: Literal["error"] = "error"
    error_details: str

# --- 代码生成与执行相关的子类 ---

class CodeGenerationStart(BaseTaskStatus):
    """表示开始生成代码。"""
    subtype: Literal["code_gen_start"] = "code_gen_start"
    reason: str = Field(description="生成代码的原因（如 'initial', 'fix_error'）。")

class CodeGenerationEnd(BaseTaskStatus):
    """表示代码生成结束。"""
    subtype: Literal["code_gen_end"] = "code_gen_end"
    code: str = Field(description="生成的完整代码。")

class CodeExecutionStart(BaseTaskStatus):
    """表示开始执行代码。"""
    subtype: Literal["code_exec_start"] = "code_exec_start"
    code_to_execute: str

class CodeExecutionEnd(BaseTaskStatus):
    """表示代码执行结束。"""
    subtype: Literal["code_exec_end"] = "code_exec_end"
    result: ExecutionResult

class PlanGenerationStart(BaseTaskStatus):
    """表示开始生成执行计划。"""
    subtype: Literal["plan_gen_start"] = "plan_gen_start"
    reason: str = Field(description="生成计划的原因（如 'initial', 'debug_fix'）。")

class PlanGenerationEnd(BaseTaskStatus):
    """表示计划生成结束。"""
    subtype: Literal["plan_gen_end"] = "plan_gen_end"
    plan: List[Dict[str, Any]] = Field(description="生成的计划步骤列表。")

class StepExecutionStart(BaseTaskStatus):
    """表示开始执行计划中的一个步骤。"""
    subtype: Literal["step_exec_start"] = "step_exec_start"
    step_index: int
    total_steps: int
    step_info: Dict[str, Any]

class StepExecutionEnd(BaseTaskStatus):
    """表示一个步骤执行结束。"""
    subtype: Literal["step_exec_end"] = "step_exec_end"
    step_index: int
    observation: str
    is_success: bool
    script: Optional[str] = Field(default=None, description="如果步骤执行生成了脚本，则包含该脚本。")

# --- 更新联合类型 ---
AnyTaskStatus = Annotated[
    Union[
        TaskStart,
        TaskEnd,
        TaskError,
        CodeGenerationStart,
        CodeGenerationEnd,
        CodeExecutionStart,
        CodeExecutionEnd,
        PlanGenerationStart,
        PlanGenerationEnd,
        StepExecutionStart,
        StepExecutionEnd,
    ],
    Field(discriminator="subtype"),
]