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
    """MCP服务器信息"""
    name: str = Field(..., description="服务器名称")
    display_name: str = Field(..., description="显示名称")
    description: str = Field(..., description="服务器描述")
    version: str = Field(..., description="版本号")
    author: str = Field(..., description="作者")
    homepage: Optional[str] = Field(None, description="主页URL")
    repository: Optional[str] = Field(None, description="代码仓库URL")
    license: Optional[str] = Field(None, description="许可证")
    tags: List[str] = Field(default_factory=list, description="标签")
    category: str = Field(..., description="分类")
    
    # 安装相关
    install_type: str = Field(..., description="安装类型: npm, pip, binary, git")
    install_command: str = Field(..., description="安装命令")
    run_command: str = Field(..., description="运行命令")
    config_schema: Optional[Dict[str, Any]] = Field(None, description="配置模式")
    
    # 工具信息
    tools: List[Dict[str, Any]] = Field(default_factory=list, description="提供的工具列表")
    resources: List[Dict[str, Any]] = Field(default_factory=list, description="提供的资源列表")
    
    # 元数据
    downloads: int = Field(default=0, description="下载次数")
    rating: float = Field(default=0.0, description="评分")
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.now)


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