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
            
            # 启动进程
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.instance.install_path
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
        """初始化MCP连接"""
        try:
            # 发送初始化请求
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
            
            response = await self._send_request(init_request)
            if not response or "error" in response:
                logger.error(f"Failed to initialize MCP connection: {response}")
                return False
            
            # 获取服务器能力
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
                "method": "tools/list"
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
                "method": "resources/list"
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
                line = await self.stdout_reader.readline()
                if not line:
                    break
                
                try:
                    message = json.loads(line.decode().strip())
                    await self._process_message(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON message: {e}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
    
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
    
    def get_tools(self) -> List[MCPTool]:
        """获取可用工具列表"""
        return self._tools.copy()
    
    def get_resources(self) -> List[MCPResource]:
        """获取可用资源列表"""
        return self._resources.copy()
    
    async def stop(self):
        """停止MCP服务器"""
        try:
            if self.process:
                # 发送终止信号
                if self.process.returncode is None:
                    self.process.terminate()
                    
                    # 等待进程结束
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        # 强制杀死进程
                        self.process.kill()
                        await self.process.wait()
                
                self.process = None
            
            # 清理资源
            if self.stdin_writer:
                self.stdin_writer.close()
                await self.stdin_writer.wait_closed()
                self.stdin_writer = None
            
            self.stdout_reader = None
            self.stderr_reader = None
            self._initialized = False
            self._tools.clear()
            self._resources.clear()
            
            # 取消所有待处理的请求
            for future in self._pending_requests.values():
                if not future.done():
                    future.cancel()
            self._pending_requests.clear()
            
            self.instance.status = MCPServerStatus.STOPPED
            self.instance.process_id = None
            
            logger.info(f"MCP server {self.instance.info.name} stopped")
            
        except Exception as e:
            logger.error(f"Error stopping MCP server: {e}")
    
    def is_running(self) -> bool:
        """检查服务器是否正在运行"""
        return (self.process is not None and 
                self.process.returncode  is None and 
                self._initialized)