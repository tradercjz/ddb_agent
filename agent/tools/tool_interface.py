
from abc import ABC, abstractmethod
from typing import List, Any, Dict
from pydantic import BaseModel, Field

from agent.execution_result import ExecutionResult

class ToolInput(BaseModel):
    pass

class BaseTool(ABC):
    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    def run(self, args: BaseModel) -> ExecutionResult:
        """Executes the tool and returns a string representation of the result."""
        pass

    def get_definition(self) -> dict:
        """Returns a JSON-serializable definition of the tool for the LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_schema.model_json_schema()
        }
    
# class PresentPlanInput(ToolInput):
#     plan: List[Dict[str, Any]] = Field(description="A step-by-step plan to accomplish the task. Each step should be a dictionary with 'step', 'thought', and 'action' details.")
#     summary: str = Field(description="A brief summary of the plan and a question to the user asking for approval.")

# # 新增一个特殊的工具类
# class PresentPlanTool(BaseTool):
#     """
#     这个工具比较特殊，它不执行外部操作，
#     而是作为AI在PLAN模式下与用户沟通的唯一渠道。
#     它的“执行结果”实际上是触发一个等待用户输入的流程。
#     """
#     name = "present_plan_and_ask_for_approval"
#     description = "Presents a detailed, step-by-step plan to the user and asks for their approval to proceed. This should be the ONLY tool used when in PLAN_MODE."
#     args_schema = PresentPlanInput

#     def run(self, args: PresentPlanInput) -> str:
#         # 这个工具的 run 方法在服务器端实际上不会返回什么有意义的东西。
#         # 它只是一个信号，告诉调用方（Agent逻辑）：“现在应该把这个计划展示给用户，并等待他们的'yes'或'no'”。
#         # 我们返回一个结构化的字符串，方便上层逻辑解析。
#         import json
#         return json.dumps({
#             "plan_presented": True,
#             "plan": args.plan,
#             "summary": args.summary
#         })