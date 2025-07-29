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
        
        return []
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
                display_name="文件系统工具",
                description="提供文件系统操作功能，包括读取、写入、搜索文件等",
                version="1.0.0",
                author="MCP Community",
                homepage="https://github.com/modelcontextprotocol/servers",
                repository="https://github.com/modelcontextprotocol/servers",
                license="MIT",
                tags=["filesystem", "files", "utility"],
                category="utility",
                install_type="npm",
                install_command="npm install -g @modelcontextprotocol/server-filesystem",
                run_command="mcp-server-filesystem",
                tools=[
                    {
                        "name": "read_file",
                        "description": "读取文件内容",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "文件路径"}
                            },
                            "required": ["path"]
                        }
                    },
                    {
                        "name": "write_file", 
                        "description": "写入文件内容",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "文件路径"},
                                "content": {"type": "string", "description": "文件内容"}
                            },
                            "required": ["path", "content"]
                        }
                    }
                ],
                downloads=1000,
                rating=4.5
            ),
            # MCPServerInfo(
            #     name="web-search",
            #     display_name="网络搜索工具",
            #     description="提供网络搜索功能，支持多种搜索引擎",
            #     version="1.2.0",
            #     author="MCP Community",
            #     homepage="https://github.com/modelcontextprotocol/servers",
            #     repository="https://github.com/modelcontextprotocol/servers",
            #     license="MIT",
            #     tags=["search", "web", "internet"],
            #     category="search",
            #     install_type="npm",
            #     install_command="npm install -g @modelcontextprotocol/server-web-search",
            #     run_command="mcp-server-web-search",
            #     config_schema={
            #         "type": "object",
            #         "properties": {
            #             "api_key": {"type": "string", "description": "搜索API密钥"},
            #             "search_engine": {"type": "string", "enum": ["google", "bing", "duckduckgo"], "default": "duckduckgo"}
            #         }
            #     },
            #     tools=[
            #         {
            #             "name": "web_search",
            #             "description": "在网络上搜索信息",
            #             "input_schema": {
            #                 "type": "object",
            #                 "properties": {
            #                     "query": {"type": "string", "description": "搜索查询"},
            #                     "max_results": {"type": "integer", "default": 10, "description": "最大结果数"}
            #                 },
            #                 "required": ["query"]
            #             }
            #         }
            #     ],
            #     downloads=800,
            #     rating=4.2
            # ),
            # MCPServerInfo(
            #     name="database",
            #     display_name="数据库工具",
            #     description="提供数据库连接和查询功能，支持多种数据库",
            #     version="2.0.0",
            #     author="MCP Community",
            #     homepage="https://github.com/modelcontextprotocol/servers",
            #     repository="https://github.com/modelcontextprotocol/servers",
            #     license="MIT",
            #     tags=["database", "sql", "data"],
            #     category="database",
            #     install_type="pip",
            #     install_command="pip install mcp-server-database",
            #     run_command="mcp-server-database",
            #     config_schema={
            #         "type": "object",
            #         "properties": {
            #             "connection_string": {"type": "string", "description": "数据库连接字符串"},
            #             "database_type": {"type": "string", "enum": ["mysql", "postgresql", "sqlite"], "description": "数据库类型"}
            #         },
            #         "required": ["connection_string", "database_type"]
            #     },
            #     tools=[
            #         {
            #             "name": "execute_query",
            #             "description": "执行SQL查询",
            #             "input_schema": {
            #                 "type": "object",
            #                 "properties": {
            #                     "query": {"type": "string", "description": "SQL查询语句"},
            #                     "params": {"type": "array", "description": "查询参数"}
            #                 },
            #                 "required": ["query"]
            #             }
            #         },
            #         {
            #             "name": "get_schema",
            #             "description": "获取数据库模式信息",
            #             "input_schema": {
            #                 "type": "object",
            #                 "properties": {
            #                     "table_name": {"type": "string", "description": "表名（可选）"}
            #                 }
            #             }
            #         }
            #     ],
            #     downloads=600,
            #     rating=4.0
            # ),
            MCPServerInfo(
                name="git",
                display_name="Git版本控制工具",
                description="提供Git版本控制操作功能",
                version="1.1.0",
                author="MCP Community",
                homepage="https://github.com/modelcontextprotocol/servers",
                repository="https://github.com/modelcontextprotocol/servers",
                license="MIT",
                tags=["git", "version-control", "development"],
                category="development",
                install_type="pip",
                install_command="pip install mcp-server-git",
                run_command="mcp-server-git",
                tools=[
                    {
                        "name": "git_status",
                        "description": "获取Git仓库状态",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "repo_path": {"type": "string", "description": "仓库路径"}
                            }
                        }
                    },
                    {
                        "name": "git_commit",
                        "description": "提交更改",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "repo_path": {"type": "string", "description": "仓库路径"},
                                "message": {"type": "string", "description": "提交信息"},
                                "files": {"type": "array", "items": {"type": "string"}, "description": "要提交的文件"}
                            },
                            "required": ["repo_path", "message"]
                        }
                    }
                ],
                downloads=450,
                rating=4.3
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