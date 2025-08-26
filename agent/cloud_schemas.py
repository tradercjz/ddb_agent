
from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any

class CloudTaskUpdate(BaseModel):
    """
    A structured message representing a progress update from a cloud operation.
    """
    status: Literal["IN_PROGRESS", "SUCCESS", "ERROR", "FINAL_LIST"]
    message: str
    details: Optional[Dict[str, Any]] = None