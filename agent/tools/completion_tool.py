from pydantic import Field
from agent.execution_result import ExecutionResult
from .tool_interface import BaseTool, ToolInput

class AttemptCompletionInput(ToolInput):
    final_answer: str = Field(description="The final, complete answer to the user's request. This should be a comprehensive summary of the results, ready to be presented to the user.")

class AttemptCompletionTool(BaseTool):
    name = "attempt_completion"
    description = (
        "Use this tool ONLY when you have successfully completed all necessary steps and have the final answer for the user. "
        "This is the very last tool you should call in your plan to conclude the task."
    )
    args_schema = AttemptCompletionInput

    def run(self, args: AttemptCompletionInput) -> ExecutionResult:
        """
        Signals that the task is complete. The data payload contains a special
        flag that the executor can use to terminate the loop gracefully.
        """
        completion_data = {
            "_is_completion_signal": True,
            "result": args.final_answer
        }
        
        return ExecutionResult(
            success=True,
            data=completion_data
        )