"""
MCP服务器运行时 - 管理单个MCP服务器的生命周期
"""

import asyncio
import json
import subprocess
import signal
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
import time
import shlex
import psutil

from ..types import MCPServerInstance, MCPServerStatus, MCPTool, MCPResource, MCPExecutionResult

# 尝试导入logger，如果失败则使用标准logging
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MCPServerRuntime:
    """MCP服务器运行时"""
    
    def __init__(self, instance: MCPServerInstance):
        self.instance = instance
        self.process: Optional[subprocess.Popen] = None
        self.stdin_writer: Optional[asyncio.StreamWriter] = None
        self.stdout_reader: Optional[asyncio.StreamReader] = None
        self.stderr_reader: Optional[asyncio.StreamReader] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._tools: List[MCPTool] = []
        self._resources: List[MCPResource] = []
        self._initialized = False
 
    async def start(self) -> bool:
        """启动MCP服务器"""
        try:
            if self.process and self.process.returncode is None:
                logger.warning(f"Server {self.instance.info.name} is already running")
                return True
            
            logger.info(f"Starting MCP server: {self.instance.info.name}")
            
            # 构建运行命令
            cmd = self._build_run_command()
            if not cmd:
                logger.error(f"Failed to build run command for {self.instance.info.name}")
                return False
            
            # 将实例中定义的环境变量覆盖/添加到 env 字典中
            env = os.environ.copy()
            env["UV_DEFAULT_INDEX"] = "https://pypi.tuna.tsinghua.edu.cn/simple"
            if self.instance.environment_variables:
                logger.info(f"Applying custom environment variables for {self.instance.info.name}")
                env.update(self.instance.environment_variables)

            #self.instance.environment_variables = env

            # 启动进程
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.instance.install_path,
                env=env
            )
            
            self.stdin_writer = self.process.stdin
            self.stdout_reader = self.process.stdout
            self.stderr_reader = self.process.stderr
            
            # 启动消息处理任务
            asyncio.create_task(self._handle_messages())
            asyncio.create_task(self._handle_stderr())
            
            # 初始化MCP连接
            if await self._initialize_connection():
                self.instance.status = MCPServerStatus.RUNNING
                self.instance.process_id = self.process.pid
                logger.info(f"MCP server {self.instance.info.name} started successfully")
                return True
            else:
                await self.stop()
                return False
                
        except Exception as e:
            logger.error(f"Failed to start MCP server {self.instance.info.name}: {e}")
            await self.stop()
            return False
    
    def _build_run_command(self) -> Optional[List[str]]:
        """构建运行命令"""
        try:
            run_cmd_base = self.instance.info.run_command

            config = self.instance.config

            cmd_parts =  [run_cmd_base]

            if isinstance(config, dict):
                for key, value in config.items():
                    cmd_parts.append(f"--{key}")
                    cmd_parts.append(str(value))
            elif isinstance(config, list):
                cmd_parts.extend(config)
            elif isinstance(config, str):
                cmd_parts.append(config)
            
            final_cmd_str = " ".join(cmd_parts)
            
            return shlex.split(final_cmd_str)
        except Exception as e:
            logger.error(f"Failed to build run command: {e}")
            return None
    
    async def _initialize_connection(self) -> bool:
        """
        初始化MCP连接。这个方法现在是完全自包含的，并在完成后设置事件。
        """
        try:
            # 等待一小段时间，确保子进程的 stdout/stdin 已经准备好
            await asyncio.sleep(0.5)

            init_request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "initialize",
                 "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {}
                    },
                    "clientInfo": {
                        "name": "ddb-agent",
                        "version": "1.0.0"
                    }
                }
            }
            
            logger.info(f"[{self.instance.info.name}] Sending 'initialize' request...")
            response = await self._send_request(init_request)
            
            if not response or "error" in response:
                logger.error(f"Failed to initialize MCP connection: {response}")
                return False
            
            logger.info(f"[{self.instance.info.name}] Sending 'initialized' notification...")
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {} 
            }
            
            await self._send_request(initialized_notification)
                
            await self._discover_capabilities()
            
            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize MCP connection: {e}")
            return False


    async def _discover_capabilities(self):
        """发现服务器能力"""
        try:
            # 获取工具列表
            tools_request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "tools/list",
                "params": {}
            }
            
            tools_response = await self._send_request(tools_request)
            if tools_response and "result" in tools_response:
                tools_data = tools_response["result"].get("tools", [])
                self._tools = [
                    MCPTool(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        server_name=self.instance.info.name,
                        input_schema=tool.get("inputSchema", {})
                    )
                    for tool in tools_data
                ]
            
            # 获取资源列表
            resources_request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "resources/list",
                "params": {}
            }
            
            resources_response = await self._send_request(resources_request)
            if resources_response and "result" in resources_response:
                resources_data = resources_response["result"].get("resources", [])
                self._resources = [
                    MCPResource(
                        uri=resource["uri"],
                        name=resource.get("name", ""),
                        description=resource.get("description"),
                        mime_type=resource.get("mimeType"),
                        server_name=self.instance.info.name
                    )
                    for resource in resources_data
                ]
            
            logger.info(f"Discovered {len(self._tools)} tools and {len(self._resources)} resources")
            
        except Exception as e:
            logger.error(f"Failed to discover capabilities: {e}")
    
    async def _send_request(self, request: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """发送JSON-RPC请求"""
        if not self.stdin_writer:
            return None
        
        try:
            request_id = request.get("id")
            if request_id is not None:
                future = asyncio.Future()
                self._pending_requests[request_id] = future
            
            # 发送请求
            message = json.dumps(request) + "\n"
            self.stdin_writer.write(message.encode())
            await self.stdin_writer.drain()
            
            if request_id is not None:
                # 等待响应
                try:
                    response = await asyncio.wait_for(future, timeout=timeout)
                    return response
                except asyncio.TimeoutError:
                    logger.error(f"Request {request_id} timed out")
                    self._pending_requests.pop(request_id, None)
                    return None
            
            return {}
            
        except Exception as e:
            logger.error(f"Failed to send request: {e}")
            return None
    
    async def _handle_messages(self):
        """处理来自服务器的消息"""
        if not self.stdout_reader:
            return
            
        try:
            while True:
                # 使用 readuntil 来读取直到换行符，这比 readline 更健-壮
                try:
                    line_bytes = await self.stdout_reader.readuntil(b'\n')
                    if not line_bytes:
                        logger.info(f"[{self.instance.info.name}] stdout stream closed.")
                        break # 流已关闭
                except asyncio.IncompleteReadError:
                    logger.warning(f"[{self.instance.info.name}] Incomplete read from stdout, stream likely closed.")
                    break

                line_str = line_bytes.decode('utf-8').strip()

                if not line_str:
                    continue

                # 尝试将该行解析为JSON。如果失败，则将其视为日志/错误信息。
                try:
                    message = json.loads(line_str)
                    # 确保解析出的是一个字典
                    if isinstance(message, dict):
                        await self._process_message(message)
                    else:
                        # 收到有效的JSON，但不是一个对象（例如，只是一个数字或字符串）
                        logger.warning(f"[{self.instance.info.name}] Received a valid but non-object JSON from stdout: {line_str}")

                except json.JSONDecodeError:
                    # 解析失败，这行不是一个有效的JSON-RPC消息。
                    # 将其记录为服务器的普通输出或启动错误。
                    logger.warning(f"[{self.instance.info.name}] Received non-JSON line from stdout (likely a log or startup error): {line_str}")
                        
                    # (理论上是底层应用问题）检查是否是已知的启动错误，并据此更新服务器状态
                    if "user name or password is incorrect" in line_str:
                        self.instance.last_error = f"DolphinDB connection failed: {line_str}"
                        self.instance.status = MCPServerStatus.ERROR
                        # 这里可以触发一个状态回调通知UI
                        
                    # 即使出错，也要继续尝试读取下一行
                    continue
                    

                except Exception as e:
                    logger.error(f"[{self.instance.info.name}] Error processing message: '{line_str}'. Error: {e}", exc_info=True)
                        
        except asyncio.CancelledError:
            logger.info(f"[{self.instance.info.name}] Message handler task cancelled.")
        except Exception as e:
            logger.error(f"[{self.instance.info.name}] Critical error in message handler: {e}", exc_info=True)
    
    async def _handle_stderr(self):
        """处理stderr输出"""
        if not self.stderr_reader:
            return
        
        try:
            while True:
                line = await self.stderr_reader.readline()
                if not line:
                    break
                
                error_msg = line.decode().strip()
                if error_msg:
                    logger.warning(f"MCP server stderr: {error_msg}")
                    
        except Exception as e:
            logger.error(f"Error in stderr handler: {e}")
    
    async def _process_message(self, message: Dict[str, Any]):
        """处理单个消息"""
        if "id" in message and message["id"] in self._pending_requests:
            # 这是对请求的响应
            future = self._pending_requests.pop(message["id"])
            if not future.done():
                future.set_result(message)
        elif "method" in message:
            # 这是服务器发起的请求或通知
            await self._handle_server_request(message)
    
    async def _handle_server_request(self, message: Dict[str, Any]):
        """处理服务器发起的请求"""
        method = message.get("method")
        
        if method == "notifications/initialized":
            logger.info("MCP server initialized")
        elif method == "logging/message":
            level = message.get("params", {}).get("level", "info")
            msg = message.get("params", {}).get("data", "")
            logger.log(level.upper(), f"MCP server log: {msg}")
        else:
            logger.debug(f"Unhandled server request: {method}")
    
    def _get_next_request_id(self) -> int:
        """获取下一个请求ID"""
        self._request_id += 1
        return self._request_id
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPExecutionResult:
        """执行工具"""
        start_time = time.time()
        
        try:
            if not self._initialized:
                return MCPExecutionResult(
                    success=False,
                    error="Server not initialized",
                    execution_time=time.time() - start_time,
                    server_name=self.instance.info.name,
                    tool_name=tool_name
                )
            
            # 检查工具是否存在
            tool = next((t for t in self._tools if t.name == tool_name), None)
            if not tool:
                return MCPExecutionResult(
                    success=False,
                    error=f"Tool '{tool_name}' not found",
                    execution_time=time.time() - start_time,
                    server_name=self.instance.info.name,
                    tool_name=tool_name
                )
            
            # 发送工具调用请求
            request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            response = await self._send_request(request)
            
            if response and "result" in response:
                return MCPExecutionResult(
                    success=True,
                    result=response["result"],
                    execution_time=time.time() - start_time,
                    server_name=self.instance.info.name,
                    tool_name=tool_name
                )
            elif response and "error" in response:
                return MCPExecutionResult(
                    success=False,
                    error=response["error"].get("message", "Unknown error"),
                    execution_time=time.time() - start_time,
                    server_name=self.instance.info.name,
                    tool_name=tool_name
                )
            else:
                return MCPExecutionResult(
                    success=False,
                    error="No response received",
                    execution_time=time.time() - start_time,
                    server_name=self.instance.info.name,
                    tool_name=tool_name
                )
                
        except Exception as e:
            return MCPExecutionResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
                server_name=self.instance.info.name,
                tool_name=tool_name
            )
    
    async def get_resource(self, uri: str) -> Optional[Dict[str, Any]]:
        """获取资源"""
        try:
            if not self._initialized:
                return None
            
            request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "resources/read",
                "params": {
                    "uri": uri
                }
            }
            
            response = await self._send_request(request)
            
            if response and "result" in response:
                return response["result"]
            else:
                return None
                
        except Exception as e:
            logger.error(f"Failed to get resource {uri}: {e}")
            return None
    
    async def get_tools(self) -> List[MCPTool]:
        """获取可用工具列表"""

        # 这里去处理，有可能是启动过程中没有拿到tools（这个可能是底层BUG，暂时不去研究了）
        # 我们在这里重新去获取
        if self._tools is None or len(self._tools) == 0:
            await self._discover_capabilities()
        return self._tools.copy()
    
    def get_resources(self) -> List[MCPResource]:
        """获取可用资源列表"""
        return self._resources.copy()
    
    async def stop(self):
        """停止MCP服务器"""
        if not self.process or self.process.returncode is not None:
            logger.info(f"Server {self.instance.info.name} is already stopped.")
            return

        logger.info(f"Attempting to stop process tree for PID: {self.process.pid}...")
        
        try:
            # 使用psutil获取父进程和所有子进程
            parent = psutil.Process(self.process.pid)
            children = parent.children(recursive=True)
            
            # 首先礼貌地终止所有子进程
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # 然后终止父进程
            try:
                parent.terminate()
            except psutil.NoSuchProcess:
                pass

            # 等待它们结束，带超时
            _, alive = psutil.wait_procs(children + [parent], timeout=3)

            # 如果还有存活的，强制杀死
            if alive:
                logger.warning(f"Processes {alive} did not terminate gracefully. Forcing kill.")
                for p in alive:
                    try:
                        p.kill()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(alive, timeout=3)

        except psutil.NoSuchProcess:
            logger.warning(f"Process with PID {self.process.pid} already gone.")
        except Exception as e:
            logger.error(f"Error stopping process tree for PID {self.process.pid}: {e}", exc_info=True)
            # 最后的保障：直接调用原始的 kill
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

        # --- 原有的清理逻辑保持不变 ---
        self.process = None
        if self.stdin_writer:
            self.stdin_writer.close()
            try:
                await self.stdin_writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.stdin_writer = None
        
        self.stdout_reader = None
        self.stderr_reader = None
        self._initialized = False
        self._tools.clear()
        self._resources.clear()
        
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
        
        self.instance.status = MCPServerStatus.STOPPED
        self.instance.process_id = None
        
        logger.info(f"MCP server {self.instance.info.name} runtime stopped.")
    
    def is_running(self) -> bool:
        """检查服务器是否正在运行"""
        return (self.process is not None and 
                self.process.returncode  is None and 
                self._initialized)