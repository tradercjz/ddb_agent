# file: agent/tool_manager.py (新建)

from agent.tools.tool_interface import BaseTool


class ToolManager:
    def __init__(self, tools: list[BaseTool]):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool_definitions(self) -> list[dict]:
        """Returns a list of all tool definitions for the Planner."""
        return [tool.get_definition() for tool in self.tools.values()]

    def call_tool(self, tool_name: str, args: dict) -> str:
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."
        tool = self.tools[tool_name]
        try:
            # Pydantic v2 用 model_validate
            validated_args = tool.args_schema.model_validate(args)
            return tool.run(validated_args)
        except Exception as e:
            return f"Error validating arguments for tool '{tool_name}': {e}"