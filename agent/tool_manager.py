# file: agent/tool_manager.py (新建)

from agent.tools.tool_interface import BaseTool, PresentPlanTool

class ToolNotFoundError(Exception):
    pass

class ToolArgumentValidationError(Exception):
    pass

class ToolManager:
    def __init__(self, tools: list[BaseTool]):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool_definitions(self, mode: str = "ACT") -> list[dict]:

        """
        根据模式返回不同的工具定义列表。
        PLAN 模式下，只暴露 'present_plan_and_ask_for_approval'。
        """
        all_tools = list(self.tools.values())
        
        all_tools.append(PresentPlanTool())

        if mode == 'PLAN':
            # 在PLAN模式下，只允许AI使用这一个“沟通”工具
            return [tool.get_definition() for tool in all_tools if tool.name == 'present_plan_and_ask_for_approval']
        else: # ACT mode
            # 在ACT模式下，暴露所有实际操作的工具
            return [tool.get_definition() for tool in all_tools if tool.name != 'present_plan_and_ask_for_approval']
       
        

    def call_tool(self, tool_name: str, args: dict) -> str:
        if tool_name not in self.tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found.")
    
        tool = self.tools[tool_name]
        try:
            # Pydantic v2 用 model_validate
            validated_args = tool.args_schema.model_validate(args)
            return tool.run(validated_args)
        except Exception as e:
            raise ToolArgumentValidationError(f"Error validating arguments for tool '{tool_name}': {e}") from e