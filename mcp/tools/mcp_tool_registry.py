"""
MCP工具注册表 - 管理MCP工具的注册和发现
"""

from typing import Dict, List, Any, Optional, Callable
import asyncio
from functools import wraps

from .mcp_tool_adapter import MCPToolAdapter, MCPToolFunction
from ..server.server_manager import MCPServerManager

from loguru import logger


class MCPToolRegistry:
    """MCP工具注册表"""
    
    def __init__(self, server_manager: MCPServerManager):
        self.server_manager = server_manager
        self.adapter = MCPToolAdapter(server_manager)
        self._registered_functions: Dict[str, MCPToolFunction] = {}
        self._auto_register_enabled = True
    
    def enable_auto_register(self, enabled: bool = True):
        """启用/禁用自动注册"""
        self._auto_register_enabled = enabled
    
    def register_all_tools(self) -> Dict[str, MCPToolFunction]:
        """注册所有可用的MCP工具"""
        self._registered_functions.clear()
        
        for tool_info in self.adapter.get_available_tools():
            tool_name = tool_info["name"]
            function = MCPToolFunction(self.adapter, tool_name)
            self._registered_functions[tool_name] = function
        
        logger.info(f"Registered {len(self._registered_functions)} MCP tools")
        return self._registered_functions.copy()
    
    def register_server_tools(self, server_name: str) -> Dict[str, MCPToolFunction]:
        """注册特定服务器的工具"""
        registered = {}
        
        for tool_info in self.adapter.get_available_tools():
            if tool_info["server_name"] == server_name:
                tool_name = tool_info["name"]
                function = MCPToolFunction(self.adapter, tool_name)
                self._registered_functions[tool_name] = function
                registered[tool_name] = function
        
        logger.info(f"Registered {len(registered)} tools from server {server_name}")
        return registered
    
    def unregister_server_tools(self, server_name: str):
        """取消注册特定服务器的工具"""
        to_remove = []
        for tool_name, function in self._registered_functions.items():
            if function.tool_info and function.tool_info["server_name"] == server_name:
                to_remove.append(tool_name)
        
        for tool_name in to_remove:
            del self._registered_functions[tool_name]
        
        logger.info(f"Unregistered {len(to_remove)} tools from server {server_name}")
    
    def get_registered_functions(self) -> Dict[str, MCPToolFunction]:
        """获取已注册的函数"""
        if self._auto_register_enabled:
            # 自动更新注册表
            self.register_all_tools()
        
        return self._registered_functions.copy()
    
    def get_function_schemas(self) -> List[Dict[str, Any]]:
        """获取所有函数的模式，用于LLM函数调用"""
        schemas = []
        for function in self.get_registered_functions().values():
            schema = function.get_function_schema()
            if schema:
                schemas.append(schema)
        return schemas
    
    def get_function_by_name(self, function_name: str) -> Optional[MCPToolFunction]:
        """根据函数名获取函数"""
        # 处理函数名转换（LLM函数名中的下划线转回点）
        if "_" in function_name and "." not in function_name:
            # 尝试找到对应的工具名
            for tool_name in self._registered_functions.keys():
                if tool_name.replace(".", "_") == function_name:
                    return self._registered_functions[tool_name]
        
        return self._registered_functions.get(function_name)
    
    async def execute_function(self, function_name: str, arguments: Dict[str, Any]) -> Any:
        """执行注册的函数"""
        function = self.get_function_by_name(function_name)
        if not function:
            raise ValueError(f"Function '{function_name}' not found in registry")
        
        return await function(**arguments)
    
    def create_llm_tools_config(self) -> List[Dict[str, Any]]:
        """创建LLM工具配置"""
        tools = []
        for function in self.get_registered_functions().values():
            schema = function.get_function_schema()
            if schema:
                tools.append({
                    "type": "function",
                    "function": schema
                })
        return tools
    
    def get_tool_help(self, tool_name: str) -> Optional[str]:
        """获取工具帮助信息"""
        return self.adapter.get_tool_help(tool_name)
    
    def list_available_tools(self) -> List[Dict[str, Any]]:
        """列出所有可用工具的信息"""
        tools_info = []
        for tool_info in self.adapter.get_available_tools():
            tools_info.append({
                "name": tool_info["name"],
                "display_name": tool_info["display_name"],
                "description": tool_info["description"],
                "server_name": tool_info["server_name"],
                "category": tool_info["category"],
                "registered": tool_info["name"] in self._registered_functions
            })
        return tools_info
    
    def get_servers_summary(self) -> Dict[str, Any]:
        """获取服务器摘要信息"""
        return self.adapter.get_servers_status()


def mcp_tool(tool_name: str, registry: MCPToolRegistry):
    """装饰器：将MCP工具包装为普通函数"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 如果函数有自定义实现，使用自定义实现
            if hasattr(func, '__code__') and func.__code__.co_code != (lambda: None).__code__.co_code:
                return await func(*args, **kwargs)
            
            # 否则使用MCP工具
            return await registry.execute_function(tool_name, kwargs)
        
        # 添加工具信息到函数
        wrapper._mcp_tool_name = tool_name
        wrapper._mcp_registry = registry
        
        return wrapper
    return decorator


class MCPToolDecorator:
    """MCP工具装饰器类"""
    
    def __init__(self, registry: MCPToolRegistry):
        self.registry = registry
    
    def tool(self, tool_name: str):
        """工具装饰器"""
        return mcp_tool(tool_name, self.registry)
    
    def auto_register(self, func):
        """自动注册装饰器"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 确保工具已注册
            if self.registry._auto_register_enabled:
                self.registry.register_all_tools()
            
            return await func(*args, **kwargs)
        
        return wrapper