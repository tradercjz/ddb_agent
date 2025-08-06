"""
MCP市场客户端 - 负责与MCP市场API交互
"""

import asyncio
import json
import os
from typing import List, Optional, Dict, Any
import aiohttp
from pathlib import Path
import time

from ..types import MCPServerInfo, MCPMarketConfig

# 尝试导入logger，如果失败则使用标准logging
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MCPMarketClient:
    """MCP市场客户端"""
    
    def __init__(self, config: MCPMarketConfig):
        self.config = config
        self.cache_file = Path(".mcp_cache/market_cache.json")
        self.cache_file.parent.mkdir(exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
    
    async def get_available_servers(self, force_refresh: bool = False) -> List[MCPServerInfo]:
        """获取可用的MCP服务器列表"""
        if not force_refresh:
            cached_servers = self._load_cache()
            if cached_servers:
                return cached_servers
        
        try:
            # 从市场API获取服务器列表
            servers = await self._fetch_servers_from_api()
            if servers:
                self._save_cache(servers)
                return servers
        except Exception as e:
            logger.error(f"Failed to fetch servers from market API: {e}")
        
        # 如果API失败，尝试加载缓存
        cached_servers = self._load_cache()
        if cached_servers:
            logger.warning("Using cached server list due to API failure")
            return cached_servers
        
        # 如果都失败了，返回内置的默认服务器列表
        return self._get_builtin_servers()
    
    async def _fetch_servers_from_api(self) -> List[MCPServerInfo]:
        """从API获取服务器列表"""
        if not self._session:
            self._session = aiohttp.ClientSession()
        
        return self._get_builtin_servers()
        async with self._session.get(f"{self.config.market_url}/api/servers") as response:
            if response.status == 200:
                data = await response.json()
                return [MCPServerInfo(**server_data) for server_data in data.get('servers', [])]
            else:
                raise Exception(f"API returned status {response.status}")
    
    def _load_cache(self) -> Optional[List[MCPServerInfo]]:
        """加载缓存的服务器列表"""
        try:
            if not self.cache_file.exists():
                return None
            
            # 检查缓存是否过期
            cache_age = time.time() - self.cache_file.stat().st_mtime
            if cache_age > self.config.cache_duration:
                return None
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [MCPServerInfo(**server_data) for server_data in data]
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
            return None
    
    def _save_cache(self, servers: List[MCPServerInfo]):
        """保存服务器列表到缓存"""
        try:
            data = [server.model_dump() for server in servers]
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    def _get_builtin_servers(self) -> List[MCPServerInfo]:
        """获取内置的默认服务器列表"""
        return [
        MCPServerInfo(
            name="filesystem",
            version="1.0.0",
            install_type="npm",
            install_command="npm install -g @modelcontextprotocol/server-filesystem",
            run_command="mcp-server-filesystem ./",
            display_name="文件系统工具",
            description="提供文件系统操作功能，包括读取、写入、搜索文件等。",
            category="utility",
            tags=["filesystem", "files", "utility"]
        ),
        MCPServerInfo(
            name="mcp-atlassian",
            version="1.1.0",
            install_type="pip",
            install_command="", 
            run_command="uvx mcp-atlassian",
            display_name="Atlassian 工具集",
            environment_variables_desc={
            },
            description="提供搜索 Jira/Confluence 等 Atlassian 产品的功能。",
            category="development",
            tags=["jira", "confluence", "development"]
        ),
        MCPServerInfo(
            name="dolphindb-mcp-server",
            version="1.1.0",
            install_type="pip",
            install_command="", 
            run_command="uvx dolphindb-mcp-server",
            display_name="DolphinDB MCP 服务器",
            description="提供对 DolphinDB 数据库进行查询和分析的功能。",
            category="database",
            tags=["dolphindb", "development", "database", "analytics"]
        )
    ]
    
    async def search_servers(self, query: str, category: Optional[str] = None, tags: Optional[List[str]] = None) -> List[MCPServerInfo]:
        """搜索MCP服务器"""
        all_servers = await self.get_available_servers()
        
        filtered_servers = []
        query_lower = query.lower() if query else ""
        
        for server in all_servers:
            # 检查查询匹配
            if query_lower:
                if not (query_lower in server.name.lower() or 
                       query_lower in server.display_name.lower() or
                       query_lower in server.description.lower()):
                    continue
            
            # 检查分类匹配
            if category and server.category != category:
                continue
            
            # 检查标签匹配
            if tags:
                if not any(tag in server.tags for tag in tags):
                    continue
            
            filtered_servers.append(server)
        
        # 按下载量和评分排序
        filtered_servers.sort(key=lambda s: (s.downloads, s.rating), reverse=True)
        return filtered_servers
    
    async def get_server_details(self, server_name: str) -> Optional[MCPServerInfo]:
        """获取特定服务器的详细信息"""
        servers = await self.get_available_servers()
        for server in servers:
            if server.name == server_name:
                return server
        return None