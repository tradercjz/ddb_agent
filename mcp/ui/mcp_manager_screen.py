"""
MCP管理界面 - 管理已安装的MCP服务器 (重构版)
"""

import asyncio
from typing import List, Optional, Dict, Any
from rich.markdown import Markdown
from rich.markup import escape

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Button, Static, DataTable, Label
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.message import Message

from ..server.server_manager import MCPServerManager
from ..market.market_manager import MCPMarketManager
from ..types import MCPServerInstance, MCPServerStatus
from .mcp_env_editor_screen import MCPEnvEditorScreen

class ServerStatusChanged(Message):
    """服务器状态变化消息"""
    def __init__(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        self.server_name = server_name
        self.status = status
        self.message = message
        super().__init__()

class MCPManagerScreen(Screen):
    """MCP管理界面 (重构版)"""
    
    BINDINGS = [
        Binding("escape", "back", "返回", show=True),
        Binding("f5", "refresh_data", "刷新", show=True),
    ]
    
    def __init__(self, server_manager: MCPServerManager, market_manager: MCPMarketManager):
        super().__init__()
        self.server_manager = server_manager
        self.market_manager = market_manager
        # 将 DataTable 作为一个类属性，方便各处访问
        self.servers_table = DataTable(id="servers-table", cursor_type="row")
        self.selected_server_name: Optional[str] = None
    
    def compose(self) -> ComposeResult:
        """创建界面布局 (极简结构)"""
        yield Header(name="MCP服务器管理")
        
        with Horizontal(id="main-container"):
            # 左栏
            with Vertical(id="left-panel"):
                yield Label("已安装服务器")
                yield self.servers_table
            
            # 右栏
            with Vertical(id="right-panel"):
                yield Label("详情与控制")
                with VerticalScroll(id="detail-scroll"):
                    yield Static("选择一个服务器查看详情", id="server-detail")
                with Horizontal(id="action-buttons"):
                    yield Button("启动", id="start-btn", disabled=True, variant="success")
                    yield Button("停止", id="stop-btn", disabled=True, variant="error")
                    yield Button("重启", id="restart-btn", disabled=True)
                    yield Button("环境变量", id="env-btn", disabled=True)
        
        yield Footer()
    
    # --- 生命周期与数据加载 ---

    def on_mount(self) -> None:
        """界面加载完成时，初始化表格并加载数据。"""
        self.log.info("MCPManagerScreen mounted. Initializing table and loading data.")
        # 1. 设置表格列
        self.servers_table.add_column("名称", key="name")
        self.servers_table.add_column("状态", key="status")
        self.servers_table.add_column("版本", key="version")
        self.servers_table.add_column("进程ID", key="pid")
        
        # 2. 异步加载数据
        self.run_worker(self.load_and_populate_table, exclusive=True)

        # 3. 注册状态回调
        self.server_manager.add_status_callback(self._on_status_change)

    async def load_and_populate_table(self) -> None:
        """从数据源加载服务器列表并填充到 DataTable 中。"""
        self.log.info("Starting to load and populate server table.")
        
        # 清空现有行，但不清除列定义
        self.servers_table.clear()
        
        try:
            installed_servers = self.market_manager.get_installed_servers()
            self.log.info(f"Found {len(installed_servers)} servers from market_manager.")
            self.log.info(f"Data: {installed_servers}")
            
            if not installed_servers:
                self.servers_table.add_row("[dim]没有已安装的服务器。[/dim]")
                return

            for server in installed_servers:
                status = self.server_manager.get_server_status(server.info.name)
                pid = self.server_manager.get_server_pid(server.info.name)

                self.servers_table.add_row(
                    server.info.display_name,
                    status.value,
                    server.info.version,
                    str(pid) if pid else "-",
                    key=server.info.name
                )
            self.log.info(f"Successfully populated table with {len(installed_servers)} rows.")

        except Exception as e:
            import traceback
            traceback.print_stack()
            self.log.error(f"Failed to load servers: {e}", exc_info=True)
            self.servers_table.add_row("[bold red]加载服务器列表失败！[/bold red]")
        
        # 加载完数据后，更新右侧面板
        await self.update_right_panel()

    async def update_right_panel(self) -> None:
        """根据当前选择，更新右侧的详情和按钮状态。"""
        detail_widget = self.query_one("#server-detail", Static)
        
        server_instance = self.market_manager.get_server_instance(self.selected_server_name) if self.selected_server_name else None

        # 更新详情
        if not server_instance:
            detail_widget.update("选择一个服务器查看详情")
        else:
            status = self.server_manager.get_server_status(server_instance.info.name)
            pid = self.server_manager.get_server_pid(server_instance.info.name)
            detail_content = f"""# {server_instance.info.display_name}
- **状态:** {status.value}
- **进程ID:** {pid if pid else '无'}
- **安装路径:** `{escape(server_instance.install_path or '未知')}`
"""
            if server_instance.environment_variables:
                detail_content += "\n## 环境变量\n"
                for key in sorted(server_instance.environment_variables.keys()):
                    detail_content += f"- **{escape(key)}:** `********`\n"
            detail_widget.update(Markdown(detail_content, code_theme="monokai"))

        # 更新按钮状态
        is_running = server_instance and self.server_manager.is_server_running(server_instance.info.name)
        is_stopped = server_instance and not is_running
        
        self.query_one("#start-btn", Button).disabled = not is_stopped
        self.query_one("#stop-btn", Button).disabled = not is_running
        self.query_one("#restart-btn", Button).disabled = not is_running
        self.query_one("#env-btn", Button).disabled = not server_instance

    # --- 事件处理 ---

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """当用户在表格中选择一行时。"""
        self.selected_server_name = event.row_key.value
        self.log.info(f"Row selected: {self.selected_server_name}")
        await self.update_right_panel()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """处理按钮点击事件。"""
        if not self.selected_server_name:
            self.notify("请先选择一个服务器", severity="warning")
            return
            
        if event.button.id == "start-btn":
            self.notify(f"正在启动 {self.selected_server_name}...")
            self.server_manager.start_server(self.selected_server_name)
        elif event.button.id == "stop-btn":
            self.notify(f"正在停止 {self.selected_server_name}...")
            self.server_manager.stop_server(self.selected_server_name)
        elif event.button.id == "restart-btn":
            self.notify(f"正在重启 {self.selected_server_name}...")
            self.server_manager.restart_server(self.selected_server_name)
        elif event.button.id == "env-btn":
            await self.action_edit_env()

    async def action_edit_env(self) -> None:
        """弹出环境变量编辑器。"""
        if not self.selected_server_name:
            return
            
        server_instance = self.market_manager.get_server_instance(self.selected_server_name)
        if not server_instance:
            return

        def on_editor_closed(result: Optional[Dict]):
            if result is None: return

            new_env_vars = result.get("env", {})
            should_restart = result.get("_restart", False)
            
            server_instance.environment_variables = new_env_vars
            self.market_manager._update_server_instance(server_instance)
            self.notify("环境变量已保存！", severity="success")

            async def update_and_maybe_restart():
                await self.update_right_panel()
                if should_restart:
                    self.notify(f"正在重启 {self.selected_server_name}...")
                    self.server_manager.restart_server(self.selected_server_name)
            
            self.run_worker(update_and_maybe_restart, exclusive=True, group="mcp_restart")

        self.app.push_screen(
            MCPEnvEditorScreen(server_instance.info.display_name, server_instance.environment_variables),
            on_editor_closed
        )

    # --- 回调与绑定 ---

    def action_refresh_data(self) -> None:
        """由 F5 绑定触发，刷新数据。"""
        self.notify("正在刷新服务器列表...")
        self.run_worker(self.load_and_populate_table, exclusive=True)

    def _on_status_change(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        """状态变化回调，从后台线程发送消息到主线程。"""
        self.post_message(ServerStatusChanged(server_name, status, message))
    
    async def on_server_status_changed(self, event: ServerStatusChanged) -> None:
        """在主线程处理状态变化消息。"""
        self.log.info(f"Received status change: {event.server_name} -> {event.status.value}")
        # 简单地重新加载整个表格来反映状态变化
        await self.load_and_populate_table()
        
        if event.message:
            severity = "information"
            if event.status == MCPServerStatus.RUNNING: severity = "success"
            if event.status == MCPServerStatus.ERROR: severity = "error"
            self.notify(f"{event.server_name}: {event.message}", severity=severity)
            
    def action_back(self) -> None:
        self.app.pop_screen()