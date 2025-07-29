"""
MCP管理界面 - 管理已安装的MCP服务器
"""

import asyncio
from typing import List, Optional, Dict, Any
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Button, Static, DataTable, 
    Label, Tabs, TabPane, Switch, Input
)
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.message import Message

from ..server.server_manager import MCPServerManager
from ..market.market_manager import MCPMarketManager
from ..types import MCPServerInstance, MCPServerStatus
from rich.markup import escape

# 尝试导入logger，如果失败则使用标准logging
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ServerStatusChanged(Message):
    """服务器状态变化消息"""
    def __init__(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        self.server_name = server_name
        self.status = status
        self.message = message
        super().__init__()


class MCPManagerScreen(Screen):
    """MCP管理界面"""
    
    BINDINGS = [
        Binding("escape", "back", "返回", show=True),
        Binding("f5", "refresh", "刷新", show=True),
        Binding("ctrl+s", "start_selected", "启动选中", show=True),
        Binding("ctrl+t", "stop_selected", "停止选中", show=True),
    ]
    
    def __init__(self, server_manager: MCPServerManager, market_manager: MCPMarketManager):
        super().__init__()
        self.server_manager = server_manager
        self.market_manager = market_manager
        self.installed_servers: List[MCPServerInstance] = []
        self.selected_server: Optional[MCPServerInstance] = None
        
        # 添加回调
        self.server_manager.add_status_callback(self._on_status_change)
    
    def compose(self) -> ComposeResult:
        """创建界面布局"""
        yield Header(name="MCP服务器管理")
        
        with Container(id="main-container"):
            with Tabs(id="main-tabs"):
                with TabPane("已安装服务器", id="servers-tab"):
                    with Horizontal(id="servers-content"):
                        # 左侧：服务器列表
                        with Vertical(id="servers-list-panel"):
                            with Horizontal(id="servers-toolbar"):
                                yield Button("刷新", id="refresh-servers-btn")
                                yield Button("启动全部", id="start-all-btn", variant="success")
                                yield Button("停止全部", id="stop-all-btn", variant="error")
                            
                            yield DataTable(id="servers-table")
                        
                        # 右侧：服务器详情和控制
                        with Vertical(id="server-control-panel"):
                            yield Label("服务器控制", id="control-label")
                            
                            with Horizontal(id="server-actions"):
                                yield Button("启动", id="start-server-btn", variant="success")
                                yield Button("停止", id="stop-server-btn", variant="error")
                                yield Button("重启", id="restart-server-btn")
                                yield Button("配置", id="config-server-btn")
                            
                            with VerticalScroll(id="server-detail-scroll"):
                                yield Static("选择一个服务器查看详情", id="server-detail")
                
                with TabPane("工具管理", id="tools-tab"):
                    with Vertical(id="tools-content"):
                        yield Label("可用工具", id="tools-label")
                        yield DataTable(id="tools-table")
                        
                        with VerticalScroll(id="tool-detail-scroll"):
                            yield Static("选择一个工具查看详情", id="tool-detail")
                
                with TabPane("系统状态", id="status-tab"):
                    with VerticalScroll(id="status-content"):
                        yield Static("", id="system-status")
        
        yield Footer()
    
    async def on_mount(self):
        """界面加载完成"""
        await self._load_installed_servers()
        await self._load_tools()
        await self._update_system_status()
    
    async def _load_installed_servers(self):
        """加载已安装的服务器"""
        try:
            servers_table = self.query_one("#servers-table", DataTable)
            servers_table.clear()
            servers_table.add_column("名称", key="name")
            servers_table.add_column("状态", key="status")
            servers_table.add_column("版本", key="version")
            servers_table.add_column("进程ID", key="pid")
            servers_table.add_column("工具数", key="tools")
            servers_table.add_column("最后使用", key="last_used")
            
            self.installed_servers = self.market_manager.get_installed_servers()
            
            for server in self.installed_servers:
                # 获取实时状态
                status = self.server_manager.get_server_status(server.info.name)
                
                # 获取工具数量
                tools_count = 0
                if status == MCPServerStatus.RUNNING:
                    tools_count = len(self.server_manager.get_server_tools(server.info.name))
                
                servers_table.add_row(
                    server.info.display_name,
                    status.value,
                    server.info.version,
                    str(server.process_id) if server.process_id else "-",
                    str(tools_count),
                    server.last_used.strftime("%Y-%m-%d %H:%M") if server.last_used else "从未",
                    key=server.info.name
                )
            
        except Exception as e:
            logger.error(f"Failed to load installed servers: {e}")
            self.notify(f"加载服务器列表失败: {str(e)}", severity="error")
    
    async def _load_tools(self):
        """加载工具列表"""
        try:
            tools_table = self.query_one("#tools-table", DataTable)
            tools_table.clear()
            tools_table.add_column("工具名", key="name")
            tools_table.add_column("服务器", key="server")
            tools_table.add_column("描述", key="description")
            tools_table.add_column("状态", key="status")
            
            all_tools = self.server_manager.get_all_tools()
            
            for tool in all_tools:
                server_status = self.server_manager.get_server_status(tool.server_name)
                status = "可用" if server_status == MCPServerStatus.RUNNING else "不可用"
                
                tools_table.add_row(
                    tool.name,
                    tool.server_name,
                    tool.description[:50] + "..." if len(tool.description) > 50 else tool.description,
                    status,
                    key=f"{tool.server_name}.{tool.name}"
                )
            
        except Exception as e:
            logger.error(f"Failed to load tools: {e}")
            self.notify(f"加载工具列表失败: {str(e)}", severity="error")
    
    async def _update_system_status(self):
        """更新系统状态"""
        try:
            status_widget = self.query_one("#system-status", Static)
            
            # 获取健康检查信息
            health_info = await self.server_manager.health_check()
            
            status_content = f"""# MCP系统状态

## 总览
- **总服务器数:** {health_info['total_servers']}
- **运行中服务器:** {health_info['running_servers']}
- **总工具数:** {len(self.server_manager.get_all_tools())}
- **总资源数:** {len(self.server_manager.get_all_resources())}

## 服务器详情
"""
            
            for server_name, server_info in health_info['servers'].items():
                status_content += f"""
### {server_name}
- **状态:** {'运行中' if server_info['running'] else '已停止'}
- **进程ID:** {server_info['process_id'] or '无'}
- **工具数:** {server_info['tools_count']}
- **资源数:** {server_info['resources_count']}
"""
            
            # 添加运行中的工具列表
            running_tools = self.server_manager.get_all_tools()
            if running_tools:
                status_content += "\n## 可用工具\n"
                for tool in running_tools:
                    status_content += f"- **{tool.name}** ({tool.server_name}): {tool.description}\n"
            
            status_widget.update(Markdown(status_content))
            
        except Exception as e:
            logger.error(f"Failed to update system status: {e}")
    
    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """表格行选择事件"""
        if event.data_table.id == "servers-table":
            server_name = event.row_key.value
            self.selected_server = next((s for s in self.installed_servers if s.info.name == server_name), None)
            await self._update_server_detail()
            await self._update_server_buttons()
        
        elif event.data_table.id == "tools-table":
            tool_key = event.row_key.value
            await self._update_tool_detail(tool_key)
    
    async def _update_server_detail(self):
        """更新服务器详情"""
        detail_widget = self.query_one("#server-detail", Static)
        
        if not self.selected_server:
            detail_widget.update("选择一个服务器查看详情")
            return
        
        server = self.selected_server
        status = self.server_manager.get_server_status(server.info.name)
        
        # 获取运行时信息
        runtime = self.server_manager.get_server_runtime(server.info.name)
        tools = runtime.get_tools() if runtime and runtime.is_running() else []
        resources = runtime.get_resources() if runtime and runtime.is_running() else []
        
        detail_content = f"""# {server.info.display_name}

## 基本信息
- **状态:** {status.value}
- **版本:** {server.info.version}
- **作者:** {server.info.author}
- **安装路径:** {server.install_path or '未知'}
- **进程ID:** {server.process_id or '无'}

## 配置信息
"""
        config = server.config 

        if isinstance(config, dict) and config:
            for key, value in config.items():
                detail_content += f"- **{escape(key)}:** {escape(str(value))}\n"
        elif isinstance(config, list) and config:
            # 将列表中的每个项作为一行显示
            for item in config:
                detail_content += f"- `{escape(str(item))}`\n"
        else:
            detail_content += "无配置信息\n"
        
        detail_content += f"""
## 运行时信息
- **工具数量:** {len(tools)}
- **资源数量:** {len(resources)}
"""
        
        if tools:
            detail_content += "\n### 可用工具\n"
            for tool in tools:
                detail_content += f"- **{tool.name}**: {tool.description}\n"
        
        if resources:
            detail_content += "\n### 可用资源\n"
            for resource in resources:
                detail_content += f"- **{resource.name}** ({resource.uri}): {resource.description or '无描述'}\n"
        
        if server.last_error:
            detail_content += f"\n## 最后错误\n```\n{server.last_error}\n```"
        
        detail_widget.update(Markdown(detail_content))
    
    async def _update_tool_detail(self, tool_key: str):
        """更新工具详情"""
        detail_widget = self.query_one("#tool-detail", Static)
        
        try:
            server_name, tool_name = tool_key.split(".", 1)
            tools = self.server_manager.get_server_tools(server_name)
            tool = next((t for t in tools if t.name == tool_name), None)
            
            if not tool:
                detail_widget.update("工具不存在")
                return
            
            detail_content = f"""# {tool.name}

**服务器:** {tool.server_name}  
**描述:** {tool.description}

## 输入参数
"""
            
            if tool.input_schema and 'properties' in tool.input_schema:
                properties = tool.input_schema['properties']
                required = tool.input_schema.get('required', [])
                
                for param_name, param_info in properties.items():
                    param_type = param_info.get('type', 'unknown')
                    param_desc = param_info.get('description', '')
                    is_required = param_name in required
                    
                    detail_content += f"- **{param_name}** ({param_type})"
                    if is_required:
                        detail_content += " [必需]"
                    if param_desc:
                        detail_content += f": {param_desc}"
                    detail_content += "\n"
            else:
                detail_content += "无参数信息\n"
            
            detail_widget.update(Markdown(detail_content))
            
        except Exception as e:
            logger.error(f"Failed to update tool detail: {e}")
            detail_widget.update(f"加载工具详情失败: {str(e)}")
    
    async def _update_server_buttons(self):
        """更新服务器控制按钮状态"""
        if not self.selected_server:
            return
        
        start_btn = self.query_one("#start-server-btn", Button)
        stop_btn = self.query_one("#stop-server-btn", Button)
        restart_btn = self.query_one("#restart-server-btn", Button)
        
        status = self.server_manager.get_server_status(self.selected_server.info.name)
        
        if status == MCPServerStatus.RUNNING:
            start_btn.disabled = True
            stop_btn.disabled = False
            restart_btn.disabled = False
        elif status == MCPServerStatus.INSTALLED:
            start_btn.disabled = False
            stop_btn.disabled = True
            restart_btn.disabled = True
        else:
            start_btn.disabled = True
            stop_btn.disabled = True
            restart_btn.disabled = True
    
    async def on_button_pressed(self, event: Button.Pressed):
        """按钮点击事件"""
        if event.button.id == "refresh-servers-btn":
            await self._refresh_all()
        elif event.button.id == "start-all-btn":
            await self._start_all_servers()
        elif event.button.id == "stop-all-btn":
            await self._stop_all_servers()
        elif event.button.id == "start-server-btn":
            await self._start_selected_server()
        elif event.button.id == "stop-server-btn":
            await self._stop_selected_server()
        elif event.button.id == "restart-server-btn":
            await self._restart_selected_server()
        elif event.button.id == "config-server-btn":
            await self._configure_selected_server()
    
    async def _refresh_all(self):
        """刷新所有数据"""
        await self._load_installed_servers()
        await self._load_tools()
        await self._update_system_status()
        self.notify("数据已刷新", severity="information")
    
    async def _start_all_servers(self):
        """启动所有服务器"""
        try:
            started_count = 0
            for server in self.installed_servers:
                if server.status == MCPServerStatus.INSTALLED:
                    success = await self.server_manager.start_server(server.info.name)
                    if success:
                        started_count += 1
            
            self.notify(f"成功启动 {started_count} 个服务器", severity="success")
            await self._refresh_all()
            
        except Exception as e:
            logger.error(f"Failed to start all servers: {e}")
            self.notify(f"启动服务器失败: {str(e)}", severity="error")
    
    async def _stop_all_servers(self):
        """停止所有服务器"""
        try:
            await self.server_manager.stop_all_servers()
            self.notify("所有服务器已停止", severity="success")
            await self._refresh_all()
            
        except Exception as e:
            logger.error(f"Failed to stop all servers: {e}")
            self.notify(f"停止服务器失败: {str(e)}", severity="error")
    
    async def _start_selected_server(self):
        """启动选中的服务器"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        try:
            success = await self.server_manager.start_server(self.selected_server.info.name)
            if success:
                self.notify(f"服务器 {self.selected_server.info.display_name} 启动成功", severity="success")
            else:
                self.notify(f"服务器 {self.selected_server.info.display_name} 启动失败", severity="error")
            
            await self._refresh_all()
            
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            self.notify(f"启动失败: {str(e)}", severity="error")
    
    async def _stop_selected_server(self):
        """停止选中的服务器"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        try:
            success = await self.server_manager.stop_server(self.selected_server.info.name)
            if success:
                self.notify(f"服务器 {self.selected_server.info.display_name} 停止成功", severity="success")
            else:
                self.notify(f"服务器 {self.selected_server.info.display_name} 停止失败", severity="error")
            
            await self._refresh_all()
            
        except Exception as e:
            logger.error(f"Failed to stop server: {e}")
            self.notify(f"停止失败: {str(e)}", severity="error")
    
    async def _restart_selected_server(self):
        """重启选中的服务器"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        try:
            success = await self.server_manager.restart_server(self.selected_server.info.name)
            if success:
                self.notify(f"服务器 {self.selected_server.info.display_name} 重启成功", severity="success")
            else:
                self.notify(f"服务器 {self.selected_server.info.display_name} 重启失败", severity="error")
            
            await self._refresh_all()
            
        except Exception as e:
            logger.error(f"Failed to restart server: {e}")
            self.notify(f"重启失败: {str(e)}", severity="error")
    
    async def _configure_selected_server(self):
        """配置选中的服务器"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        # 这里可以打开一个配置对话框
        self.notify("配置功能开发中...", severity="information")
    
    def _on_status_change(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        """状态变化回调"""
        self.post_message(ServerStatusChanged(server_name, status, message))
    
    async def on_server_status_changed(self, event: ServerStatusChanged):
        """处理状态变化消息"""
        # 刷新数据
        await self._refresh_all()
        
        # 如果是当前选中的服务器，更新按钮状态
        if self.selected_server and self.selected_server.info.name == event.server_name:
            await self._update_server_buttons()
        
        # 显示通知
        if event.message:
            severity = "success" if event.status == MCPServerStatus.RUNNING else "information"
            if event.status == MCPServerStatus.ERROR:
                severity = "error"
            
            self.notify(f"{event.server_name}: {event.message}", severity=severity)
    
    def action_back(self):
        """返回上一级"""
        self.dismiss()
    
    def action_refresh(self):
        """刷新"""
        asyncio.create_task(self._refresh_all())
    
    def action_start_selected(self):
        """启动选中的服务器"""
        asyncio.create_task(self._start_selected_server())
    
    def action_stop_selected(self):
        """停止选中的服务器"""
        asyncio.create_task(self._stop_selected_server())