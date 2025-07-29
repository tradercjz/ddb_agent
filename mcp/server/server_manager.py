"""
MCP服务器管理器 - 统一管理所有MCP服务器的运行时
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable, Union
from pathlib import Path

from .server_runtime import MCPServerRuntime
from ..types import MCPServerInstance, MCPServerStatus, MCPTool, MCPResource, MCPExecutionResult
from ..market.market_manager import MCPMarketManager

# 尝试导入logger，如果失败则使用标准logging
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    print("import looger error, use standard logging")
    import logging
    logger = logging.getLogger(__name__)


class MCPServerManager:
    """MCP服务器管理器"""
    
    def __init__(self, market_manager: Optional[MCPMarketManager] = None):
        self.market_manager = market_manager or MCPMarketManager()
        self.runtimes: Dict[str, MCPServerRuntime] = {}
        self._status_callbacks: List[Callable[[str, MCPServerStatus, Optional[str]], None]] = []
    
    def add_status_callback(self, callback: Callable[[str, MCPServerStatus, Optional[str]], None]):
        """添加状态变化回调"""
        self._status_callbacks.append(callback)
    
    def _notify_status_change(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        """通知状态变化"""
        for callback in self._status_callbacks:
            try:
                callback(server_name, status, message)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    async def start_server(self, server_name: str, config: Optional[Union[Dict[str, Any], List[str], str]] = None) -> bool:
        """启动MCP服务器"""
        try:
            # 检查服务器是否已在运行
            if server_name in self.runtimes:
                runtime = self.runtimes[server_name]
                if runtime.is_running():
                    logger.warning(f"Server {server_name} is already running")
                    return True
                else:
                    # 清理旧的运行时
                    await runtime.stop()
                    del self.runtimes[server_name]
            
            # 获取服务器实例
            instance = self.market_manager.get_server_instance(server_name)
            if not instance:
                logger.error(f"Server {server_name} is not installed")
                return False
            
            if instance.status != MCPServerStatus.INSTALLED:
                logger.error(f"Server {server_name} is not in installed state: {instance.status}")
                return False
            
            # 更新配置
            if config:
                instance.config = config
            
            # 创建运行时
            runtime = MCPServerRuntime(instance)
            
            # 启动服务器
            self._notify_status_change(server_name, MCPServerStatus.INSTALLING, "正在启动服务器...")
            
            success = await runtime.start()
            
            if success:
                self.runtimes[server_name] = runtime
                self._notify_status_change(server_name, MCPServerStatus.RUNNING, "服务器已启动")
                
                # 更新市场管理器中的实例状态
                instance.status = MCPServerStatus.RUNNING
                instance.process_id = runtime.process.pid if runtime.process else None
                self.market_manager._update_server_instance(instance)
                
                logger.info(f"MCP server {server_name} started successfully")
                return True
            else:
                self._notify_status_change(server_name, MCPServerStatus.ERROR, "启动失败")
                return False
                
        except Exception as e:
            logger.error(f"Failed to start server {server_name}: {e}")
            self._notify_status_change(server_name, MCPServerStatus.ERROR, f"启动失败: {str(e)}")
            return False
    
    async def stop_server(self, server_name: str) -> bool:
        """停止MCP服务器"""
        try:
            if server_name not in self.runtimes:
                logger.warning(f"Server {server_name} is not running")
                return True
            
            runtime = self.runtimes[server_name]
            
            self._notify_status_change(server_name, MCPServerStatus.INSTALLING, "正在停止服务器...")
            
            await runtime.stop()
            del self.runtimes[server_name]
            
            # 更新市场管理器中的实例状态
            instance = self.market_manager.get_server_instance(server_name)
            if instance:
                instance.status = MCPServerStatus.STOPPED
                instance.process_id = None
                self.market_manager._update_server_instance(instance)
            
            self._notify_status_change(server_name, MCPServerStatus.STOPPED, "服务器已停止")
            logger.info(f"MCP server {server_name} stopped successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop server {server_name}: {e}")
            self._notify_status_change(server_name, MCPServerStatus.ERROR, f"停止失败: {str(e)}")
            return False
        
    async def bootstrap_builtin_servers(self, auto_start: bool = True):
        """
        引导内置的MCP服务器，确保它们已安装并（可选择地）正在运行。
        """
        logger.info("Bootstrapping built-in MCP servers...")
        builtin_servers_info = self.market_manager.get_builtin_servers()

        for server_info in builtin_servers_info:
            server_name = server_info.name
            instance = self.market_manager.get_server_instance(server_name)

            # 步骤 1: 检查并安装
            # 如果服务器未安装或处于错误状态，则尝试安装
            if instance is None or instance.status == MCPServerStatus.ERROR:
                logger.info(f"Built-in server '{server_name}' not installed or in error state. Attempting installation.")
                try:
                    install_success = await self.market_manager.install_server(server_name)
                    if not install_success:
                        logger.error(f"Failed to auto-install built-in server '{server_name}'. Skipping.")
                        continue
                except Exception as e:
                    logger.error(f"Exception during auto-installation of '{server_name}': {e}")
                    continue
            
            # 步骤 2: (可选) 检查并启动
            if auto_start:
                if not self.is_server_running(server_name):
                    logger.info(f"Built-in server '{server_name}' is not running. Attempting to start.")
                    try:
                        start_success = await self.start_server(server_name)
                        if not start_success:
                             logger.error(f"Failed to auto-start built-in server '{server_name}'.")
                    except Exception as e:
                        logger.error(f"Exception during auto-start of '{server_name}': {e}")

        logger.info("Built-in MCP servers bootstrap process completed.")
    
    
    async def restart_server(self, server_name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """重启MCP服务器"""
        logger.info(f"Restarting MCP server: {server_name}")
        
        # 先停止
        await self.stop_server(server_name)
        
        # 等待一下确保完全停止
        await asyncio.sleep(1)
        
        # 再启动
        return await self.start_server(server_name, config)
    
    def get_running_servers(self) -> List[str]:
        """获取正在运行的服务器列表"""
        return [name for name, runtime in self.runtimes.items() if runtime.is_running()]
    
    def is_server_running(self, server_name: str) -> bool:
        """检查服务器是否正在运行"""
        runtime = self.runtimes.get(server_name)
        return runtime is not None and runtime.is_running()
    
    def get_server_runtime(self, server_name: str) -> Optional[MCPServerRuntime]:
        """获取服务器运行时"""
        return self.runtimes.get(server_name)
    
    def execute_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> MCPExecutionResult:
        """执行MCP工具"""
        try:
            runtime = self.runtimes.get(server_name)
            if not runtime:
                return MCPExecutionResult(
                    success=False,
                    error=f"Server '{server_name}' is not running",
                    execution_time=0.0,
                    server_name=server_name,
                    tool_name=tool_name
                )
            
            if not runtime.is_running():
                return MCPExecutionResult(
                    success=False,
                    error=f"Server '{server_name}' is not in running state",
                    execution_time=0.0,
                    server_name=server_name,
                    tool_name=tool_name
                )
            
            return runtime.execute_tool(tool_name, arguments)
            
        except Exception as e:
            logger.error(f"Failed to execute tool {tool_name} on server {server_name}: {e}")
            return MCPExecutionResult(
                success=False,
                error=str(e),
                execution_time=0.0,
                server_name=server_name,
                tool_name=tool_name
            )
    
    async def get_resource(self, server_name: str, uri: str) -> Optional[Dict[str, Any]]:
        """获取MCP资源"""
        try:
            runtime = self.runtimes.get(server_name)
            if not runtime or not runtime.is_running():
                logger.error(f"Server '{server_name}' is not running")
                return None
            
            return await runtime.get_resource(uri)
            
        except Exception as e:
            logger.error(f"Failed to get resource {uri} from server {server_name}: {e}")
            return None
    
    def get_all_tools(self) -> List[MCPTool]:
        """获取所有运行中服务器的工具"""
        all_tools = []
        for runtime in self.runtimes.values():
            if runtime.is_running():
                all_tools.extend(runtime.get_tools())
        return all_tools
    
    def get_server_tools(self, server_name: str) -> List[MCPTool]:
        """获取特定服务器的工具"""
        runtime = self.runtimes.get(server_name)
        if runtime and runtime.is_running():
            return runtime.get_tools()
        return []
    
    def get_all_resources(self) -> List[MCPResource]:
        """获取所有运行中服务器的资源"""
        all_resources = []
        for runtime in self.runtimes.values():
            if runtime.is_running():
                all_resources.extend(runtime.get_resources())
        return all_resources
    
    def get_server_resources(self, server_name: str) -> List[MCPResource]:
        """获取特定服务器的资源"""
        runtime = self.runtimes.get(server_name)
        if runtime and runtime.is_running():
            return runtime.get_resources()
        return []
    
    async def stop_all_servers(self):
        """停止所有服务器"""
        logger.info("Stopping all MCP servers...")
        
        stop_tasks = []
        for server_name in list(self.runtimes.keys()):
            stop_tasks.append(self.stop_server(server_name))
        
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        logger.info("All MCP servers stopped")
    
    def get_server_status(self, server_name: str) -> MCPServerStatus:
        """获取服务器状态"""
        instance = self.market_manager.get_server_instance(server_name)
        if not instance:
            return MCPServerStatus.AVAILABLE
        
        # 检查运行时状态
        runtime = self.runtimes.get(server_name)
        if runtime and runtime.is_running():
            return MCPServerStatus.RUNNING
        elif instance.status == MCPServerStatus.RUNNING:
            # 状态不一致，更新为停止状态
            instance.status = MCPServerStatus.STOPPED
            self.market_manager._update_server_instance(instance)
            return MCPServerStatus.STOPPED
        
        return instance.status
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        health_info = {
            "total_servers": len(self.runtimes),
            "running_servers": len(self.get_running_servers()),
            "servers": {}
        }
        
        for server_name, runtime in self.runtimes.items():
            health_info["servers"][server_name] = {
                "running": runtime.is_running(),
                "tools_count": len(runtime.get_tools()),
                "resources_count": len(runtime.get_resources()),
                "process_id": runtime.instance.process_id
            }
        
        return health_info