# file: agent/execution_result.py

from pydantic import BaseModel
from typing import Any, Optional

class ExecutionResult(BaseModel):
    """
    A structured container for the result of executing a code script.
    """
    success: bool
    executed_script: Optional[str] = None 
    data: Optional[Any] = None
    error_message: Optional[str] = None
    
    # 我们甚至可以预留一些元数据字段，比如执行耗时等
    metadata: Optional[dict] = None