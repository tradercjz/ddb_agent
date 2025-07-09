# file: agent/tools/tool_interface.py (新建)
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

class ToolInput(BaseModel):
    pass

class BaseTool(ABC):
    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    def run(self, args: BaseModel) -> str:
        """Executes the tool and returns a string representation of the result."""
        pass

    def get_definition(self) -> dict:
        """Returns a JSON-serializable definition of the tool for the LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_schema.model_json_schema()
        }