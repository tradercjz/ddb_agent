
from .tool_interface import BaseTool, ToolInput, ExecutionResult
from pydantic import Field
from typing import List, Dict, Any, Optional

class PlanModeResponseInput(ToolInput):
    response: str = Field(description="The response to provide to the user, typically a plan or a clarifying question.")
    options: Optional[List[str]] = Field(None, description="A list of 2-5 options for the user to choose from, simplifying their response.")

class PlanModeResponseTool(BaseTool):
    name = "plan_mode_response"
    description = "Presents a plan or asks a clarifying question to the user and waits for their input. This is the primary tool for communication in PLAN_MODE."
    args_schema = PlanModeResponseInput

    def run(self, args: PlanModeResponseInput) -> ExecutionResult:
        """
        This tool's execution is special. It doesn't perform an action but signals
        the executor to pause and wait for user interaction.
        """
        # The result data is a structured dictionary that the executor will interpret
        # as an interactive prompt for the user.
        interactive_data = {
            "_is_interactive_request": True, # A special flag to identify this tool's purpose
            "type": "USER_INTERACTION",
            "message": args.response,
            "options": args.options or []
        }
        
        return ExecutionResult(
            success=True,
            data=interactive_data
        )