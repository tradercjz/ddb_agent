"""
MCP相关的数据类型定义
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
from enum import Enum
import datetime


class MCPServerStatus(str, Enum):
    """MCP服务器状态"""
    AVAILABLE = "available"      # 可用但未安装
    INSTALLING = "installing"    # 正在安装
    INSTALLED = "installed"      # 已安装但未运行
    RUNNING = "running"         # 正在运行
    STOPPED = "stopped"         # 已停止
    ERROR = "error"             # 错误状态
    UPDATING = "updating"       # 正在更新


class MCPServerInfo(BaseModel):
    """
    一个 MCP 服务器的核心操作信息。
    这是 Agent 从市场获取并用于实际安装和运行服务器的精简数据结构。
    """
    # --- 核心操作字段 ---
    name: str = Field(..., description="服务器的唯一标识符，例如 'filesystem'。")
    install_type: str = Field(..., description="安装类型，如 'npm', 'pip', 'git'。Agent 根据此字段决定安装策略。")
    install_command: str = Field(..., description="完整的安装命令，例如 'npm install -g @mcp/server-filesystem'。")
    run_command: str = Field(..., description="启动服务器的命令，例如 'mcp-server-filesystem ./'。")
    version: str = Field(..., description="服务器的版本号，用于检查更新和依赖管理。")
    environment_variables_desc: Dict[str, str] = Field(
        default_factory=dict,
        description="需要设置的环境变量参考和描述"
    )

    # --- 用于市场发现与UI展示的字段 (Agent 本身不直接使用，但从市场 API 一并获取) ---
    display_name: str = Field(..., description="用于在UI中展示的、更友好的名称。")
    description: str = Field(..., description="服务器功能的简短描述，帮助用户理解其用途。")
    category: Optional[str] = Field("other", description="服务器的分类，如 'utility', 'database', 'ai'。")
    tags: Optional[List[str]] = Field(default_factory=list, description="用于搜索和筛选的标签列表。")
    
    # --- (可选) 丰富元数据，用于市场UI ---
    # 这些字段可以由市场 API 提供，但 Agent 的核心逻辑不依赖它们。
    author: Optional[str] = Field(None, description="作者或组织。")
    repository: Optional[str] = Field(None, description="代码仓库 URL。")
    license: Optional[str] = Field(None, description="软件许可证。")


class MCPServerInstance(BaseModel):
    """MCP服务器实例"""
    info: MCPServerInfo
    status: MCPServerStatus = MCPServerStatus.AVAILABLE
    install_path: Optional[str] = None
    config: Optional[Union[Dict[str, Any], List[str], str]] = Field(
        default=None, 
        description="服务器配置，可以是键值对字典或命令行参数列表"
    )
    environment_variables: Dict[str, str] = Field(
        default_factory=dict,
        description="为该服务器实例设置的特定环境变量"
    )
    process_id: Optional[int] = None
    port: Optional[int] = None
    last_error: Optional[str] = None
    installed_at: Optional[datetime.datetime] = None
    last_used: Optional[datetime.datetime] = None


class MCPTool(BaseModel):
    """MCP工具定义"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    server_name: str = Field(..., description="所属服务器名称")
    input_schema: Dict[str, Any] = Field(..., description="输入参数模式")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="输出模式")


class MCPResource(BaseModel):
    """MCP资源定义"""
    uri: str = Field(..., description="资源URI")
    name: str = Field(..., description="资源名称")
    description: Optional[str] = Field(None, description="资源描述")
    mime_type: Optional[str] = Field(None, description="MIME类型")
    server_name: str = Field(..., description="所属服务器名称")


class MCPMarketConfig(BaseModel):
    """MCP市场配置"""
    market_url: str = Field(default="https://mcp-market.playddb.com", description="市场API地址")
    cache_duration: int = Field(default=3600, description="缓存持续时间（秒）")
    auto_update: bool = Field(default=True, description="是否自动更新市场信息")
    install_dir: str = Field(default=".mcp_servers", description="服务器安装目录")
    max_concurrent_installs: int = Field(default=3, description="最大并发安装数")


class MCPExecutionResult(BaseModel):
    """MCP工具执行结果"""
    success: bool = Field(..., description="是否成功")
    result: Any = Field(None, description="执行结果")
    error: Optional[str] = Field(None, description="错误信息")
    execution_time: float = Field(..., description="执行时间（秒）")
    server_name: str = Field(..., description="执行的服务器名称")
    tool_name: str = Field(..., description="执行的工具名称")