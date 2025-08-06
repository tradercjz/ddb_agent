# file: mcp/server/server_manager.py

"""
MCP服务器管理器 - 作为同步接口，将所有异步操作委托给 MCPAsyncIOManager。
"""

import time
from typing import Dict, List, Optional, Any, Callable, Union

# 导入我们的新异步核心和相关类型
from mcp.async_io_manager import MCPAsyncIOManager
from ..types import MCPServerInstance, MCPServerStatus, MCPTool, MCPResource, MCPExecutionResult
from ..market.market_manager import MCPMarketManager

# 日志记录器
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MCPServerManager:
    """MCP服务器管理器 (同步门面)"""
    
    def __init__(self, market_manager: Optional[MCPMarketManager] = None):
        self.market_manager = market_manager or MCPMarketManager()
        self._status_callbacks: List[Callable[[str, MCPServerStatus, Optional[str]], None]] = []
        
        # 内部持有一个异步管理器实例，并将自身的回调转发方法传给它
        self._async_manager = MCPAsyncIOManager(self.market_manager, self._on_status_change_from_async)
        # 启动后台线程
        self._async_manager.start()
    
    def _on_status_change_from_async(self, server_name: str, status: MCPServerStatus, message: Optional[str]):
        """
        一个回调函数，用于接收来自后台异步管理器的状态更新，
        并将其转发给注册到本同步管理器的回调。
        这个方法是在后台线程中被调用的。
        """
        self._notify_status_change(server_name, status, message)

    def add_status_callback(self, callback: Callable[[str, MCPServerStatus, Optional[str]], None]):
        """
        注册一个回调函数，以便在服务器状态发生变化时收到通知。
        注意：回调函数可能在后台线程中被调用，如果需要更新UI，请确保是线程安全的。
        """
        self._status_callbacks.append(callback)
    
    def _notify_status_change(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        """将状态变化通知所有注册的回调。"""
        for callback in self._status_callbacks:
            try:
                callback(server_name, status, message)
            except Exception as e:
                logger.error(f"Status callback for '{server_name}' failed: {e}")

    def shutdown(self):
        """
        安全地关闭管理器，停止后台线程和所有服务器。
        应该在应用程序退出时调用此方法。
        """
        logger.info("Shutting down MCPServerManager and all running servers...")
        self._async_manager.stop()
        logger.info("MCPServerManager shut down successfully.")


    def get_server_pid(self, server_name: str) -> Optional[int]:
        """
        同步获取正在运行的服务器的进程 ID (PID)。
        如果服务器未运行，则返回 None。
        """
        if not self.is_server_running(server_name):
            return None
        return self._async_manager.get_server_pid(server_name)
    
    def start_server(self, server_name: str, config: Optional[Union[Dict[str, Any], List[str], str]] = None) -> None:
        # 返回值改为 None
        logger.info(f"Requesting to start server: {server_name}")
        try:
            self._async_manager.start_server(server_name, config=config)
        except Exception as e:
            logger.error(f"Failed to post start command for server {server_name}: {e}", exc_info=True)
            self._notify_status_change(server_name, MCPServerStatus.ERROR, f"发送启动命令失败: {str(e)}")

    def stop_server(self, server_name: str) -> None:
        # 返回值改为 None
        logger.info(f"Requesting to stop server: {server_name}")
        try:
            self._async_manager.stop_server(server_name)
        except Exception as e:
            logger.error(f"Failed to post stop command for server {server_name}: {e}", exc_info=True)
            self._notify_status_change(server_name, MCPServerStatus.ERROR, f"发送停止命令失败: {str(e)}")

    def bootstrap_builtin_servers(self, auto_start: bool = True):
        """同步引导内置的MCP服务器。"""
        logger.info("Requesting to bootstrap built-in servers...")
        try:
            # 这是一个“即发即忘”的操作，因为它可能耗时较长
            # 如果需要等待完成，_async_manager 需要返回结果
            self._async_manager.bootstrap_builtin_servers(auto_start=auto_start)
        except Exception as e:
            logger.error(f"Failed to bootstrap servers: {e}", exc_info=True)

    def restart_server(self, server_name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """同步重启MCP服务器。"""
        logger.info(f"Requesting to restart server: {server_name}")
        try:
            self.stop_server(server_name)
            time.sleep(1) # 给一点时间确保进程完全关闭
            return self.start_server(server_name, config)
        except Exception as e:
            logger.error(f"Failed to restart server {server_name}: {e}", exc_info=True)
            return False
    
    def get_running_servers(self) -> List[str]:
        """获取正在运行的服务器列表。"""
        return self._async_manager.get_running_servers()
    
    def is_server_running(self, server_name: str) -> bool:
        """检查服务器是否正在运行。"""
        return self._async_manager.is_server_running(server_name)

    def execute_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> MCPExecutionResult:
        """同步执行MCP工具。"""
        try:
            return self._async_manager.execute_tool(server_name, tool_name, arguments)
        except Exception as e:
            logger.error(f"Failed to execute tool {tool_name} on server {server_name}: {e}", exc_info=True)
            return MCPExecutionResult(
                success=False,
                error=f"Critical error in MCPServerManager: {str(e)}",
                execution_time=0.0,
                server_name=server_name,
                tool_name=tool_name
            )

    def get_resource(self, server_name: str, uri: str) -> Optional[Dict[str, Any]]:
        """同步获取MCP资源。"""
        try:
            return self._async_manager.get_resource(server_name, uri)
        except Exception as e:
            logger.error(f"Failed to get resource {uri} from server {server_name}: {e}", exc_info=True)
            return None
    
    def get_all_tools(self) -> List[MCPTool]:
        """获取所有运行中服务器的工具。"""
        return self._async_manager.get_all_tools()
    
    def get_server_tools(self, server_name: str) -> List[MCPTool]:
        """获取特定服务器的工具。"""
        return self._async_manager.get_server_tools(server_name)
    
    def get_all_resources(self) -> List[MCPResource]:
        """获取所有运行中服务器的资源。"""
        return self._async_manager.get_all_resources()

    def get_server_resources(self, server_name: str) -> List[MCPResource]:
        """获取特定服务器的资源。"""
        # 这个方法没有在 async_manager 中实现，但可以基于其他方法构建
        runtime = self._async_manager.runtimes.get(server_name)
        return runtime.get_resources() if runtime and runtime.is_running() else []

    def stop_all_servers(self):
        """同步停止所有服务器。"""
        logger.info("Requesting to stop all servers...")
        try:
            self._async_manager.stop_all_servers()
        except Exception as e:
            logger.error(f"An error occurred while stopping all servers: {e}", exc_info=True)
    
    def get_server_status(self, server_name: str) -> MCPServerStatus:
        """
        获取服务器的当前状态。
        首先检查实时运行时状态，如果未运行，则查询磁盘上的持久化状态。
        """
        if self.is_server_running(server_name):
            return MCPServerStatus.RUNNING
        
        instance = self.market_manager.get_server_instance(server_name)
        if not instance:
            return MCPServerStatus.AVAILABLE
        
        # 修正可能的状态不一致：如果磁盘记录是 RUNNING 但实际没有运行
        if instance.status == MCPServerStatus.RUNNING:
            instance.status = MCPServerStatus.STOPPED
            self.market_manager._update_server_instance(instance)

        return instance.status
    
    def health_check(self) -> Dict[str, Any]:
        """同步进行健康检查。"""
        return self._async_manager.health_check()