import asyncio
import threading
import uuid
import time
from queue import Queue, Empty
from typing import Dict, Any, Optional, List, Callable

from .server.server_runtime import MCPServerRuntime
from .types import MCPServerStatus, MCPTool, MCPResource, MCPExecutionResult
from .market.market_manager import MCPMarketManager

# 日志配置
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MCPAsyncIOManager:
    """
    在专用后台线程中运行 asyncio 事件循环，处理所有 MCP 服务器的异步操作。
    这个类是线程安全的，设计为从同步代码中调用。
    """
    def __init__(self, market_manager: MCPMarketManager, status_callback: Optional[Callable] = None):
        self.market_manager = market_manager
        self.status_callback = status_callback
        
        self.request_queue = Queue()
        self._response_dict: Dict[str, Any] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.runtimes: Dict[str, MCPServerRuntime] = {}
        self._runtimes_lock = threading.Lock()

    def _run_event_loop(self):
        """
        后台线程的目标函数，负责创建和运行事件循环。
        """
        try:
            logger.info("AsyncIOManager thread started.")
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # 启动周期性任务来处理来自主线程的请求
            self._loop.create_task(self._request_processor_task())
            
            # 运行事件循环，直到 stop() 被调用
            self._loop.run_forever()
            
            logger.info("AsyncIOManager event loop stopped. Cleaning up...")
        finally:
            # 循环结束后进行彻底的清理
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            
            # 优雅地关闭所有正在运行的服务器
            cleanup_coro = self._shutdown_all_servers_async()
            self._loop.run_until_complete(cleanup_coro)
            
            tasks = asyncio.all_tasks(self._loop)
            for task in tasks:
                task.cancel()
            
            async def gather_cancelled():
                await asyncio.gather(*tasks, return_exceptions=True)

            self._loop.run_until_complete(gather_cancelled())
            self._loop.close()
            logger.info("AsyncIOManager thread finished.")

    async def _request_processor_task(self):
        """
        在事件循环中运行的后台任务，负责处理请求队列。
        """
        while not self._stop_event.is_set():
            try:
                # 使用 get_nowait 避免阻塞事件循环
                request_id, command, args, kwargs = self.request_queue.get_nowait()
                
                logger.debug(f"Processing command '{command}' with ID {request_id}")
                
                result = None
                error = None
                try:
                    # 获取命令对应的异步方法
                    handler = getattr(self, f"_{command}_async")
                    # 执行异步方法
                    result = await handler(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error executing command '{command}': {e}", exc_info=True)
                    error = e
                
                # 将结果/错误放回响应字典，通知主线程
                self._response_dict[request_id] = (result, error)

            except Empty:
                # 队列为空是正常情况，短暂休眠让出控制权
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                logger.info("Request processor task cancelled.")
                break

    def start(self):
        """启动后台线程和事件循环。"""
        if self._thread and self._thread.is_alive():
            logger.warning("AsyncIOManager is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_event_loop, name="MCPAsyncIOManagerThread", daemon=True)
        self._thread.start()
        
        # 等待事件循环成功启动
        while self._loop is None or not self._loop.is_running():
            time.sleep(0.01)
        logger.info("AsyncIOManager started successfully.")

    def stop(self):
        """平滑地停止后台线程和事件循环。"""
        if not self._thread or not self._thread.is_alive():
            logger.warning("AsyncIOManager is not running.")
            return
            
        logger.info("Stopping AsyncIOManager...")
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            # 安排事件循环停止
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        # 等待线程结束
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            logger.error("AsyncIOManager thread did not stop gracefully.")
        
        self._thread = None
        self._loop = None

    def _send_command(self, command: str, *args, timeout: float = 600.0, **kwargs) -> Any:
        """
        从主线程（同步）发送命令到后台线程（异步）并阻塞等待结果。
        """
        if not self._thread or not self._thread.is_alive():
            raise RuntimeError("MCPAsyncIOManager is not running. Call start() first.")
        
        request_id = str(uuid.uuid4())
        self.request_queue.put((request_id, command, args, kwargs))
        
        # 使用带超时的循环来等待结果
        start_time = time.time()
        while time.time() - start_time < timeout:
            if request_id in self._response_dict:
                result, error = self._response_dict.pop(request_id)
                if error:
                    raise error
                return result
            time.sleep(0.01) # 释放GIL，让后台线程有机会运行
        
        raise TimeoutError(f"Command '{command}' timed out after {timeout} seconds.")

    # ===================================================================
    # == 对外暴露的同步接口 (这些是 MCPServerManager 应该调用的方法) ==
    # ===================================================================

    def start_server(self, server_name: str, config: Optional[Any] = None) -> bool:
        return self._send_command('start_server', server_name, config=config)

    def stop_server(self, server_name: str) -> bool:
        return self._send_command('stop_server', server_name)
    
    def execute_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> MCPExecutionResult:
        return self._send_command('execute_tool', server_name, tool_name, arguments)

    def bootstrap_builtin_servers(self, auto_start: bool = True):
        return self._send_command('bootstrap_builtin_servers', auto_start=auto_start)

    def get_running_servers(self) -> List[str]:
        return self._send_command('get_running_servers')

    def is_server_running(self, server_name: str) -> bool:
        # 这个可以直接查询，因为 runtimes 的读操作是相对安全的
        runtime = self.runtimes.get(server_name)
        return runtime is not None and runtime.is_running()
    
    def get_all_tools(self) -> List[MCPTool]:
        return self._send_command('get_all_tools')

    def get_server_tools(self, server_name: str) -> List[MCPTool]:
        return self._send_command('get_server_tools', server_name)

    def stop_all_servers(self):
        return self._send_command('stop_all_servers')
        
    def health_check(self) -> Dict[str, Any]:
        return self._send_command('health_check')

    def get_resource(self, server_name: str, uri: str) -> Optional[Dict[str, Any]]:
        return self._send_command('get_resource', server_name, uri)

    # ==============================================================
    # == 内部异步实现 (这些方法只在后台的事件循环中被调用) ==
    # ==============================================================

    async def _start_server_async(self, server_name: str, config: Optional[Any] = None) -> bool:
        with self._runtimes_lock:
            if server_name in self.runtimes and self.runtimes[server_name].is_running():
                logger.warning(f"Server {server_name} is already running.")
                return True

        if self.status_callback:
            self.status_callback(server_name, MCPServerStatus.INSTALLING, "正在启动...")

        instance = self.market_manager.get_server_instance(server_name)
        
        if config:
            instance.config = config

        runtime = MCPServerRuntime(instance)
        success = await runtime.start()

        if success:
            with self._runtimes_lock:
                self.runtimes[server_name] = runtime
            instance.status = MCPServerStatus.RUNNING
            if self.status_callback:
                self.status_callback(server_name, MCPServerStatus.RUNNING, "服务器已启动")
        else:
            instance.status = MCPServerStatus.ERROR
            if self.status_callback:
                self.status_callback(server_name, MCPServerStatus.ERROR, "启动失败")
        
        self.market_manager._update_server_instance(instance)
        return success

    def get_server_pid(self, server_name: str) -> Optional[int]:
        """线程安全地获取指定服务器的 PID。"""
        with self._runtimes_lock:
            runtime = self.runtimes.get(server_name)
            if runtime and runtime.is_running():
                return runtime.process.pid # 直接从 process 对象获取
        return None
    
    async def _stop_server_async(self, server_name: str) -> bool:
        with self._runtimes_lock:
            runtime = self.runtimes.get(server_name)
        if not runtime:
            logger.warning(f"Server {server_name} not found in runtimes, cannot stop.")
            return True

        await runtime.stop()

        with self._runtimes_lock:
            self.runtimes.pop(server_name, None)
        
        instance = self.market_manager.get_server_instance(server_name)
        if instance:
            instance.status = MCPServerStatus.STOPPED
            self.market_manager._update_server_instance(instance)
            
        if self.status_callback:
            self.status_callback(server_name, MCPServerStatus.STOPPED, "服务器已停止")
        return True

    async def _execute_tool_async(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> MCPExecutionResult:
        runtime = self.runtimes.get(server_name)
        if runtime and runtime.is_running():
            return await runtime.execute_tool(tool_name, arguments)
        else:
            return MCPExecutionResult(
                success=False,
                error=f"Server '{server_name}' is not running.",
                execution_time=0.0,
                server_name=server_name,
                tool_name=tool_name
            )

    async def _shutdown_all_servers_async(self):
        tasks = [self._stop_server_async(name) for name in list(self.runtimes.keys())]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _bootstrap_builtin_servers_async(self, auto_start: bool = True):
        servers_info = self.market_manager.get_builtin_servers()
        for server_info in servers_info:
            instance = self.market_manager.get_server_instance(server_info.name)
            if not instance or instance.status == MCPServerStatus.ERROR:
                logger.info(f"Bootstrapping: Installing {server_info.name}...")
                # 假设 install_server 也是 async
                install_success = await self.market_manager.install_server(server_info.name)
                if not install_success: continue
                
            if auto_start and not self.is_server_running(server_info.name):
                logger.info(f"Bootstrapping: Starting {server_info.name}...")
                await self._start_server_async(server_info.name)
        logger.info("Bootstrap complete.")

    async def _get_running_servers_async(self) -> List[str]:
        return [name for name, rt in self.runtimes.items() if rt.is_running()]

    async def _get_all_tools_async(self) -> List[MCPTool]:
        all_tools = []
        for runtime in self.runtimes.values():
            if runtime.is_running():
                all_tools.extend(await runtime.get_tools())
        return all_tools

    async def _get_server_tools_async(self, server_name: str) -> List[MCPTool]:
        runtime = self.runtimes.get(server_name)
        return await runtime.get_tools() if runtime and runtime.is_running() else []

    async def _stop_all_servers_async(self):
        tasks = [self._stop_server_async(name) for name in list(self.runtimes.keys())]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
    async def _health_check_async(self) -> Dict[str, Any]:
        running_servers = self._get_running_servers_async()
        return {
            "total_servers": len(self.runtimes),
            "running_servers": len(await running_servers),
            # ... etc.
        }

    async def _get_resource_async(self, server_name: str, uri: str) -> Optional[Dict[str, Any]]:
        runtime = self.runtimes.get(server_name)
        if runtime and runtime.is_running():
            return await runtime.get_resource(uri)
        return None