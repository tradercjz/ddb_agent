# file: agent/tool_manager_enhanced.py

from typing import Optional, Dict, Any, List
import asyncio
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

class EnhancedToolManager:
    """增强的工具管理器，支持MCP工具"""
    
    def __init__(self, tools: list[BaseTool], mcp_market_manager: Optional[MCPMarketManager] = None, mcp_server_manager: Optional[MCPServerManager] = None, enable_mcp: bool = False):
        self.tools = {tool.name: tool for tool in tools}
        self.enable_mcp = enable_mcp
        self.mcp_market_manager = mcp_market_manager
        self.mcp_server_manager = mcp_server_manager
        self.mcp_tool_adapter = MCPToolAdapter(self.mcp_server_manager)
        self.mcp_tool_registry = MCPToolRegistry(self.mcp_server_manager)

        
    
    # def _initialize_mcp(self):
    #     """初始化MCP组件"""
    #     try:
    #         self.mcp_market_manager = MCPMarketManager()
    #         self.mcp_server_manager = MCPServerManager(self.mcp_market_manager)
    #         self.mcp_tool_adapter = MCPToolAdapter(self.mcp_server_manager)
    #         self.mcp_tool_registry = MCPToolRegistry(self.mcp_server_manager)

    #         self.mcp_server_manager.bootstrap_builtin_servers()
    #     except Exception as e:
    #         print(f"Warning: Failed to initialize MCP components: {e}")
    #         self.enable_mcp = False

    def get_tool_definitions(self, mode: str = "ACT") -> list[dict]:
        """
        根据模式返回不同的工具定义列表。
        PLAN 模式下，只暴露 'present_plan_and_ask_for_approval'。
        """
        all_tools = list(self.tools.values())
        all_tools.append(PresentPlanTool())

        # 获取MCP工具定义
        mcp_tools = []
        if self.enable_mcp and self.mcp_tool_adapter:
            try:
                mcp_tool_infos = self.mcp_tool_adapter.get_available_tools()
                for tool_info in mcp_tool_infos:
                    mcp_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool_info["name"].replace(".", "_"),  # LLM函数名不能包含点
                            "description": f"[MCP] {tool_info['description']} (来自 {tool_info['server_name']})",
                            "parameters": tool_info["input_schema"]
                        }
                    })
            except Exception as e:
                print(f"Warning: Failed to get MCP tools: {e}")

        if mode == 'PLAN':
            # 在PLAN模式下，只允许AI使用这一个"沟通"工具
            return [tool.get_definition() for tool in all_tools if tool.name == 'present_plan_and_ask_for_approval']
        else: # ACT mode
            # 在ACT模式下，暴露所有实际操作的工具，包括MCP工具
            base_tools = [tool.get_definition() for tool in all_tools if tool.name != 'present_plan_and_ask_for_approval']
            return base_tools + mcp_tools

    def call_tool(self, tool_name: str, args: dict) -> ExecutionResult:
        """调用工具（支持异步MCP工具）"""
        # 检查是否是MCP工具
        print(">>>>call_tool entered")
        if self.enable_mcp and "_" in tool_name and tool_name not in self.tools:
            # 可能是MCP工具（函数名中的点被替换为下划线）
            return self._call_mcp_tool(tool_name, args)
        
        # 调用常规工具
        if tool_name not in self.tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found.")
    
        tool = self.tools[tool_name]
        try:
            # Pydantic v2 用 model_validate
            validated_args = tool.args_schema.model_validate(args)
            return tool.run(validated_args)
        except Exception as e:
            raise ToolArgumentValidationError(f"Error validating arguments for tool '{tool_name}': {e}") from e
    
    def _call_mcp_tool(self, tool_name: str, args: dict) -> ExecutionResult:
        """调用MCP工具"""
        try:
            if not self.mcp_tool_adapter:
                raise ToolNotFoundError("MCP is not available")
            
            # 将函数名转换回工具名（下划线转点）
            mcp_tool_name = tool_name.replace("_", ".")
            
            # 验证工具是否存在
            tool_info = self.mcp_tool_adapter.get_tool_by_name(mcp_tool_name)
            if not tool_info:
                # 尝试直接查找
                available_tools = self.mcp_tool_adapter.get_available_tools()
                for tool in available_tools:
                    if tool["name"].replace(".", "_") == tool_name:
                        mcp_tool_name = tool["name"]
                        break
                else:
                    raise ToolNotFoundError(f"MCP tool '{tool_name}' not found")
            
            # 执行MCP工具
            result = self.mcp_tool_adapter.execute_tool(mcp_tool_name, args)
            
            # 转换为ExecutionResult格式
            return ExecutionResult(
                success=result.success,
                data=result.result,
                output=str(result.result) if result.result is not None else "",
                error=result.error
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=f"MCP tool execution failed: {str(e)}"
            )
    
    def get_mcp_market_manager(self) -> Optional[MCPMarketManager]:
        """获取MCP市场管理器"""
        return self.mcp_market_manager
    
    def get_mcp_server_manager(self) -> Optional[MCPServerManager]:
        """获取MCP服务器管理器"""
        return self.mcp_server_manager
    
    def get_mcp_tool_adapter(self) -> Optional[MCPToolAdapter]:
        """获取MCP工具适配器"""
        return self.mcp_tool_adapter
    
    def get_mcp_tool_registry(self) -> Optional[MCPToolRegistry]:
        """获取MCP工具注册表"""
        return self.mcp_tool_registry
    
    def is_mcp_enabled(self) -> bool:
        """检查MCP是否启用"""
        return self.enable_mcp
    
    def get_all_tool_names(self) -> List[str]:
        """获取所有可用工具名称"""
        tool_names = list(self.tools.keys())
        
        if self.enable_mcp and self.mcp_tool_adapter:
            try:
                mcp_tools = self.mcp_tool_adapter.get_available_tools()
                for tool in mcp_tools:
                    tool_names.append(tool["name"].replace(".", "_"))
            except Exception:
                pass
        
        return tool_names
    
    def get_tool_help(self, tool_name: str) -> Optional[str]:
        """获取工具帮助信息"""
        # 检查常规工具
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            return f"**{tool.name}**\n\n{tool.description}"
        
        # 检查MCP工具
        if self.enable_mcp and self.mcp_tool_adapter:
            try:
                mcp_tool_name = tool_name.replace("_", ".")
                return self.mcp_tool_adapter.get_tool_help(mcp_tool_name)
            except Exception:
                pass
        
        return None
    
    async def cleanup(self):
        """清理资源"""
        if self.enable_mcp and self.mcp_server_manager:
            try:
                await self.mcp_server_manager.stop_all_servers()
            except Exception as e:
                print(f"Warning: Failed to stop MCP servers during cleanup: {e}")