from pydantic import BaseModel, Field
from typing import Optional, List

class Snippet(BaseModel):
    """Represents a user-defined code snippet."""
    name: str = Field(description="A short, memorable name for the snippet (e.g., 'create_trade_table'). This will be the trigger.")
    content: str = Field(description="The actual code content of the snippet.")
    description: Optional[str] = Field(None, description="A brief explanation of what the snippet does.")
    tags: List[str] = Field(default_factory=list, description="Tags for easy searching (e.g., ['table', 'trade', 'sample_data']).")