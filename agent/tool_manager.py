# file: agent/tool_manager.py (新建)

from typing import Optional, Dict, Any, List
from agent.execution_result import ExecutionResult
from agent.tools.tool_interface import BaseTool, PresentPlanTool

# MCP相关导入
try:
    from mcp.server.server_manager import MCPServerManager
    from mcp.market.market_manager import MCPMarketManager
    from mcp.tools.mcp_tool_adapter import MCPToolAdapter
    from mcp.tools.mcp_tool_registry import MCPToolRegistry
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

class ToolNotFoundError(Exception):
    pass

class ToolArgumentValidationError(Exception):
    pass

class ToolManager:
    def __init__(self, tools: list[BaseTool], enable_mcp: bool = True):
        self.tools = {tool.name: tool for tool in tools}
        self.enable_mcp = enable_mcp and MCP_AVAILABLE
        
        # MCP相关组件
        self.mcp_market_manager: Optional[MCPMarketManager] = None
        self.mcp_server_manager: Optional[MCPServerManager] = None
        self.mcp_tool_adapter: Optional[MCPToolAdapter] = None
        self.mcp_tool_registry: Optional[MCPToolRegistry] = None
        
        if self.enable_mcp:
            self._initialize_mcp()
    
    def _initialize_mcp(self):
        """初始化MCP组件"""
        try:
            self.mcp_market_manager = MCPMarketManager()
            self.mcp_server_manager = MCPServerManager(self.mcp_market_manager)
            self.mcp_tool_adapter = MCPToolAdapter(self.mcp_server_manager)
            self.mcp_tool_registry = MCPToolRegistry(self.mcp_server_manager)
        except Exception as e:
            print(f"Warning: Failed to initialize MCP components: {e}")
            self.enable_mcp = False

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
       
        

    def call_tool(self, tool_name: str, args: dict) -> ExecutionResult:
        if tool_name not in self.tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found.")
    
        tool = self.tools[tool_name]
        try:
            # Pydantic v2 用 model_validate
            validated_args = tool.args_schema.model_validate(args)
            return tool.run(validated_args)
        except Exception as e:
            raise ToolArgumentValidationError(f"Error validating arguments for tool '{tool_name}': {e}") from e