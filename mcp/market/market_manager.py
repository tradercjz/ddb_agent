"""
MCP市场管理器 - 统一管理MCP市场相关功能
"""

import asyncio
from typing import List, Optional, Dict, Any, Callable, Union
from pathlib import Path
import json

from .market_client import MCPMarketClient
from ..types import MCPServerInfo, MCPMarketConfig, MCPServerInstance, MCPServerStatus

# 尝试导入logger，如果失败则使用标准logging
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MCPMarketManager:
    """MCP市场管理器"""
    
    def __init__(self, config: Optional[MCPMarketConfig] = None):
        self.config = config or MCPMarketConfig()
        self.client = MCPMarketClient(self.config)
        self.installed_servers_file = Path(".mcp_cache/installed_servers.json")
        self.installed_servers_file.parent.mkdir(exist_ok=True)
        
        # 事件回调
        self._status_callbacks: List[Callable[[str, MCPServerStatus, Optional[str]], None]] = []
        self._progress_callbacks: List[Callable[[str, float, str], None]] = []
    
    def add_status_callback(self, callback: Callable[[str, MCPServerStatus, Optional[str]], None]):
        """添加状态变化回调"""
        self._status_callbacks.append(callback)
    
    def add_progress_callback(self, callback: Callable[[str, float, str], None]):
        """添加进度回调"""
        self._progress_callbacks.append(callback)
    
    def _notify_status_change(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        """通知状态变化"""
        for callback in self._status_callbacks:
            try:
                callback(server_name, status, message)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    def _notify_progress(self, server_name: str, progress: float, message: str):
        """通知进度变化"""
        for callback in self._progress_callbacks:
            try:
                callback(server_name, progress, message)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    async def get_available_servers(self, force_refresh: bool = False) -> List[MCPServerInfo]:
        """获取可用的MCP服务器列表"""
        async with self.client:
            return await self.client.get_available_servers(force_refresh)
        
    def get_builtin_servers(self) -> List[MCPServerInfo]:
        """获取内置的默认服务器列表，不通过网络。"""
        # 这个方法直接从 client 获取硬编码的列表
        return self.client._get_builtin_servers()
    
    async def search_servers(self, query: str = "", category: Optional[str] = None, tags: Optional[List[str]] = None) -> List[MCPServerInfo]:
        """搜索MCP服务器"""
        async with self.client:
            return await self.client.search_servers(query, category, tags)
    
    async def get_server_details(self, server_name: str) -> Optional[MCPServerInfo]:
        """获取服务器详细信息"""
        async with self.client:
            return await self.client.get_server_details(server_name)
    
    def get_installed_servers(self) -> List[MCPServerInstance]:
        """获取已安装的服务器列表"""
        try:
            if not self.installed_servers_file.exists():
                return []
            
            with open(self.installed_servers_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [MCPServerInstance(**instance_data) for instance_data in data]
        except Exception as e:
            logger.error(f"Failed to load installed servers: {e}")
            return []
    
    def _save_installed_servers(self, servers: List[MCPServerInstance]):
        """保存已安装服务器列表"""
        try:
            data = [server.model_dump(mode='json') for server in servers]
            with open(self.installed_servers_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save installed servers: {e}")
    
    def get_server_instance(self, server_name: str) -> Optional[MCPServerInstance]:
        """获取特定服务器实例"""
        installed_servers = self.get_installed_servers()
        for server in installed_servers:
            if server.info.name == server_name:
                return server
        return None
    

    async def install_server(self, server_name: str, config: Optional[Union[Dict[str, Any], List[str]]] = None) -> bool:
        """安装MCP服务器"""
        try:
            # 获取服务器信息
            server_info = await self.get_server_details(server_name)
            if not server_info:
                logger.error(f"Server {server_name} not found in market")
                return False
            
            # 检查是否已安装
            existing_instance = self.get_server_instance(server_name)
            if existing_instance and existing_instance.status != MCPServerStatus.ERROR:
                logger.warning(f"Server {server_name} is already installed")
                return True
            
            # 创建服务器实例
            instance = MCPServerInstance(
                info=server_info,
                status=MCPServerStatus.INSTALLING,
                config=config
            )
            
            # 更新状态
            self._notify_status_change(server_name, MCPServerStatus.INSTALLING, "开始安装...")
            self._notify_progress(server_name, 0.1, "准备安装环境...")
            
            # 执行安装
            success = await self._execute_install(instance)
            
            if success:
                instance.status = MCPServerStatus.INSTALLED
                instance.install_path = str(Path(self.config.install_dir) / server_name)
                self._notify_status_change(server_name, MCPServerStatus.INSTALLED, "安装完成")
                self._notify_progress(server_name, 1.0, "安装完成")
            else:
                instance.status = MCPServerStatus.ERROR
                instance.last_error = "安装失败"
                self._notify_status_change(server_name, MCPServerStatus.ERROR, "安装失败")
            
            # 保存实例
            self._update_server_instance(instance)
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to install server {server_name}: {e}")
            self._notify_status_change(server_name, MCPServerStatus.ERROR, f"安装失败: {str(e)}")
            return False
    
    async def _execute_install(self, instance: MCPServerInstance) -> bool:
        """执行实际的安装过程"""
        import subprocess
        import os
        
        try:
            install_dir = Path(self.config.install_dir) / instance.info.name
            install_dir.mkdir(parents=True, exist_ok=True)
            
            self._notify_progress(instance.info.name, 0.3, "执行安装命令...")
            
            # 根据安装类型执行不同的安装命令
            if instance.info.install_type == "npm":
                # NPM安装
                process = await asyncio.create_subprocess_shell(
                    instance.info.install_command,
                    cwd=str(install_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    self._notify_progress(instance.info.name, 0.8, "安装完成，验证安装...")
                    return True
                else:
                    logger.error(f"Install failed: {stderr.decode()}")
                    instance.last_error = stderr.decode()
                    return False
                    
            elif instance.info.install_type == "pip":
                # Python包安装
                process = await asyncio.create_subprocess_shell(
                    instance.info.install_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    self._notify_progress(instance.info.name, 0.8, "安装完成，验证安装...")
                    return True
                else:
                    logger.error(f"Install failed: {stderr.decode()}")
                    instance.last_error = stderr.decode()
                    return False
                    
            elif instance.info.install_type == "git":
                # Git克隆安装
                repo_url = instance.info.install_command.replace("git clone ", "")
                process = await asyncio.create_subprocess_shell(
                    f"git clone {repo_url} .",
                    cwd=str(install_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    self._notify_progress(instance.info.name, 0.8, "克隆完成，安装依赖...")
                    
                    # 尝试安装依赖
                    if (install_dir / "package.json").exists():
                        npm_process = await asyncio.create_subprocess_shell(
                            "npm install",
                            cwd=str(install_dir),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        await npm_process.communicate()
                    elif (install_dir / "requirements.txt").exists():
                        pip_process = await asyncio.create_subprocess_shell(
                            "pip install -r requirements.txt",
                            cwd=str(install_dir),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        await pip_process.communicate()
                    
                    return True
                else:
                    logger.error(f"Git clone failed: {stderr.decode()}")
                    instance.last_error = stderr.decode()
                    return False
            
            else:
                logger.error(f"Unsupported install type: {instance.info.install_type}")
                return False
                
        except Exception as e:
            logger.error(f"Install execution failed: {e}")
            instance.last_error = str(e)
            return False
    
    def _update_server_instance(self, instance: MCPServerInstance):
        """更新服务器实例"""
        installed_servers = self.get_installed_servers()
        
        # 查找并更新现有实例，或添加新实例
        updated = False
        for i, server in enumerate(installed_servers):
            if server.info.name == instance.info.name:
                installed_servers[i] = instance
                updated = True
                break
        
        if not updated:
            installed_servers.append(instance)
        
        self._save_installed_servers(installed_servers)
    
    async def uninstall_server(self, server_name: str) -> bool:
        """卸载MCP服务器"""
        try:
            instance = self.get_server_instance(server_name)
            if not instance:
                logger.warning(f"Server {server_name} is not installed")
                return True
            
            self._notify_status_change(server_name, MCPServerStatus.INSTALLING, "正在卸载...")
            
            # 停止服务器（如果正在运行）
            if instance.status == MCPServerStatus.RUNNING:
                from ..server.server_manager import MCPServerManager
                server_manager = MCPServerManager()
                await server_manager.stop_server(server_name)
            
            # 删除安装目录
            if instance.install_path:
                import shutil
                install_path = Path(instance.install_path)
                if install_path.exists():
                    shutil.rmtree(install_path)
            
            # 从已安装列表中移除
            installed_servers = self.get_installed_servers()
            installed_servers = [s for s in installed_servers if s.info.name != server_name]
            self._save_installed_servers(installed_servers)
            
            self._notify_status_change(server_name, MCPServerStatus.AVAILABLE, "卸载完成")
            return True
            
        except Exception as e:
            logger.error(f"Failed to uninstall server {server_name}: {e}")
            self._notify_status_change(server_name, MCPServerStatus.ERROR, f"卸载失败: {str(e)}")
            return False
    
    def get_categories(self) -> List[str]:
        """获取所有可用的分类"""
        # 这里可以从市场API获取，现在返回常见分类
        return [
            "utility",      # 实用工具
            "search",       # 搜索工具
            "database",     # 数据库工具
            "development",  # 开发工具
            "ai",          # AI工具
            "communication", # 通信工具
            "media",       # 媒体工具
            "finance",     # 金融工具
            "productivity", # 生产力工具
            "other"        # 其他
        ]
    
    def get_popular_tags(self) -> List[str]:
        """获取热门标签"""
        return [
            "filesystem", "files", "utility", "search", "web", "internet",
            "database", "sql", "data", "git", "version-control", "development",
            "ai", "ml", "nlp", "communication", "chat", "email",
            "media", "image", "video", "finance", "trading", "productivity"
        ]