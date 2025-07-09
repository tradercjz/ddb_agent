# file: agent/coding_task_state.py

from pydantic import BaseModel, Field
from typing import List, Optional

from agent.execution_result import ExecutionResult

class CodingTaskState(BaseModel):
    """
    Manages the state of a single, iterative coding task.
    This object is passed through the execution loop.
    """
    original_query: str
    current_code: str = ""
    
    # 记录每次执行的结果，形成调试历史
    execution_history: List[ExecutionResult] = Field(default_factory=list)
    
    # 用于RAG的上下文，可以在循环中更新
    rag_context: str = ""
    
    # 控制循环次数
    refinement_attempts: int = 0
    max_attempts: int = 5

    @property
    def has_reached_max_attempts(self) -> bool:
        """Check if the task has run out of refinement attempts."""
        return self.refinement_attempts >= self.max_attempts
    
    def add_execution_result(self, result: ExecutionResult):
        """Adds a new execution result to the history."""
        self.execution_history.append(result)

    def get_last_error(self) -> Optional[str]:
        """Convenience method to get the last error message, if any."""
        if not self.execution_history:
            return None
        last_result = self.execution_history[-1]
        return last_result.error_message if not last_result.success else None