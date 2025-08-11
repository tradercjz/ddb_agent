"""
MCP工具适配器 - 将MCP工具集成到现有的工具系统中
"""

from typing import Dict, Any, List, Optional, Callable
import json
import asyncio

from ..server.server_manager import MCPServerManager
from ..types import MCPTool, MCPExecutionResult

# 尝试导入工具接口，如果失败则创建简单版本
try:
    from agent.tools.tool_interface import ToolInterface, ToolResult
except ImportError:
    class ToolInterface:
        pass
    
    class ToolResult:
        def __init__(self, success: bool, result: Any = None, error: str = None, metadata: dict = None):
            self.success = success
            self.result = result
            self.error = error
            self.metadata = metadata or {}  # 避免默认是 None


from loguru import logger


class MCPToolAdapter(ToolInterface):
    """MCP工具适配器"""
    
    def __init__(self, server_manager: MCPServerManager):
        self.server_manager = server_manager
        self._tool_cache: Dict[str, MCPTool] = {}
        self._update_tool_cache()
    
    def _update_tool_cache(self):
        """更新工具缓存"""
        self._tool_cache.clear()
        for tool in self.server_manager.get_all_tools():
            # 使用 server_name.tool_name 作为唯一标识
            tool_id = f"{tool.server_name}.{tool.name}"
            self._tool_cache[tool_id] = tool
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取可用的MCP工具列表"""
        self._update_tool_cache()
        
        tools = []
        for tool_id, tool in self._tool_cache.items():
            tools.append({
                "name": tool_id,
                "display_name": f"{tool.name} ({tool.server_name})",
                "description": tool.description,
                "server_name": tool.server_name,
                "tool_name": tool.name,
                "input_schema": tool.input_schema,
                "category": "mcp"
            })
        
        return tools
    
    def get_tool_by_name(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """根据名称获取工具信息"""
        self._update_tool_cache()
        
        tool = self._tool_cache.get(tool_name)
        if tool:
            return {
                "name": tool_name,
                "display_name": f"{tool.name} ({tool.server_name})",
                "description": tool.description,
                "server_name": tool.server_name,
                "tool_name": tool.name,
                "input_schema": tool.input_schema,
                "category": "mcp"
            }
        return None
    
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """执行MCP工具"""
        try:
            # 解析工具名称
            if "." not in tool_name:
                return ToolResult(
                    success=False,
                    result=None,
                    error=f"Invalid MCP tool name format: {tool_name}. Expected format: server_name.tool_name"
                )
            
            server_name, actual_tool_name = tool_name.split(".", 1)
            
            # 检查服务器是否运行
            if not self.server_manager.is_server_running(server_name):
                return ToolResult(
                    success=False,
                    result=None,
                    error=f"MCP server '{server_name}' is not running"
                )
            
            # 执行工具
            result = self.server_manager.execute_tool(server_name, actual_tool_name, arguments)
            
            return ToolResult(
                success=result.success,
                result=result.result,
                error=result.error,
                metadata={
                    "server_name": result.server_name,
                    "tool_name": result.tool_name,
                    "execution_time": result.execution_time
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to execute MCP tool {tool_name}: {e}")
            return ToolResult(
                success=False,
                result=None,
                error=str(e)
            )
    
    def validate_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证工具参数"""
        try:
            tool = self._tool_cache.get(tool_name)
            if not tool:
                return False, f"Tool '{tool_name}' not found"
            
            # 基本的JSON Schema验证
            schema = tool.input_schema
            if not schema:
                return True, None
            
            # 检查必需参数
            required_fields = schema.get("required", [])
            for field in required_fields:
                if field not in arguments:
                    return False, f"Missing required parameter: {field}"
            
            # 检查参数类型（简单验证）
            properties = schema.get("properties", {})
            for arg_name, arg_value in arguments.items():
                if arg_name in properties:
                    expected_type = properties[arg_name].get("type")
                    if expected_type:
                        if not self._validate_type(arg_value, expected_type):
                            return False, f"Parameter '{arg_name}' should be of type {expected_type}"
            
            return True, None
            
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """验证值的类型"""
        type_mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict
        }
        
        expected_python_type = type_mapping.get(expected_type)
        if expected_python_type:
            return isinstance(value, expected_python_type)
        
        return True  # 未知类型，跳过验证
    
    def get_tool_help(self, tool_name: str) -> Optional[str]:
        """获取工具帮助信息"""
        tool = self._tool_cache.get(tool_name)
        if not tool:
            return None
        
        help_text = f"**{tool.name}** (来自 {tool.server_name})\n\n"
        help_text += f"{tool.description}\n\n"
        
        if tool.input_schema:
            help_text += "**参数:**\n"
            properties = tool.input_schema.get("properties", {})
            required = tool.input_schema.get("required", [])
            
            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "unknown")
                param_desc = param_info.get("description", "")
                is_required = param_name in required
                
                help_text += f"- `{param_name}` ({param_type})"
                if is_required:
                    help_text += " **[必需]**"
                if param_desc:
                    help_text += f": {param_desc}"
                help_text += "\n"
        
        return help_text
    
    def get_servers_status(self) -> Dict[str, Any]:
        """获取所有MCP服务器状态"""
        return {
            "running_servers": self.server_manager.get_running_servers(),
            "total_tools": len(self._tool_cache),
            "servers_detail": {
                server_name: {
                    "tools": [tool.name for tool in self.server_manager.get_server_tools(server_name)],
                    "resources": len(self.server_manager.get_server_resources(server_name))
                }
                for server_name in self.server_manager.get_running_servers()
            }
        }


class MCPToolFunction:
    """MCP工具函数包装器，用于LLM函数调用"""
    
    def __init__(self, adapter: MCPToolAdapter, tool_name: str):
        self.adapter = adapter
        self.tool_name = tool_name
        self.tool_info = adapter.get_tool_by_name(tool_name)
    
    async def __call__(self, **kwargs) -> Any:
        """执行MCP工具"""
        result = await self.adapter.execute_tool(self.tool_name, kwargs)
        
        if result.success:
            return result.result
        else:
            raise Exception(f"MCP tool execution failed: {result.error}")
    
    def get_function_schema(self) -> Dict[str, Any]:
        """获取函数模式，用于LLM函数调用"""
        if not self.tool_info:
            return {}
        
        return {
            "name": self.tool_name.replace(".", "_"),  # LLM函数名不能包含点
            "description": self.tool_info["description"],
            "parameters": self.tool_info["input_schema"]
        }