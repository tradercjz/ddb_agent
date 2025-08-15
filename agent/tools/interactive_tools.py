
from .tool_interface import BaseTool, ToolInput, ExecutionResult
from pydantic import Field
from typing import List, Dict, Any, Optional

class AskForHumanFeedbackInput(ToolInput):
    message: str = Field(description="An informative message explaining the error or the situation requiring feedback.")
    options: Optional[List[str]] = Field(None, description="A list of suggested actions for the user to choose from, e.g., ['Retry', 'Abort'].")

class AskForHumanFeedbackTool(BaseTool):
    name = "ask_for_human_feedback"
    description = (
        "Presents an error or an unexpected situation to the user and asks for guidance on how to proceed. "
        "Use this tool ONLY when an action has failed and you need help deciding the next step."
    )
    args_schema = AskForHumanFeedbackInput

    def run(self, args: AskForHumanFeedbackInput) -> ExecutionResult:
        """
        Signals the executor to pause and wait for human input regarding an error.
        """
        interactive_data = {
            "_is_interactive_request": True,
            "type": "USER_INTERACTION",
            "message": args.message,
            "options": args.options or [],
            "_is_error_feedback": True 
        }
        
        return ExecutionResult(
            success=True,
            data=interactive_data
        )

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