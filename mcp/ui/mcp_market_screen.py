"""
MCP市场界面 - 浏览和安装MCP服务器
"""

import asyncio
from typing import List, Optional, Dict, Any
from rich.text import Text
from rich.panel import Panel
from rich.columns import Columns
from rich.table import Table
from rich.markdown import Markdown
from rich.spinner import Spinner

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Input, Button, Static, DataTable, 
    SelectionList, Label, Tabs, TabPane, ProgressBar
)
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.message import Message

from mcp.server.server_manager import MCPServerManager
from mcp.ui.mcp_env_editor_screen import MCPEnvEditorScreen

from ..market.market_manager import MCPMarketManager
from ..types import MCPServerInfo, MCPServerStatus

# 尝试导入logger，如果失败则使用标准logging
try:
    from utils.logger import setup_llm_logger
    logger = setup_llm_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ServerInstallProgress(Message):
    """服务器安装进度消息"""
    def __init__(self, server_name: str, progress: float, message: str):
        self.server_name = server_name
        self.progress = progress
        self.message = message
        super().__init__()


class ServerStatusChanged(Message):
    """服务器状态变化消息"""
    def __init__(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        self.server_name = server_name
        self.status = status
        self.message = message
        super().__init__()


class MCPMarketScreen(Screen):
    """MCP市场界面"""
    
    BINDINGS = [
        Binding("escape", "back", "返回", show=True),
        Binding("f5", "refresh", "刷新", show=True),
        Binding("ctrl+i", "install_selected", "安装选中", show=True),
    ]
    
    def __init__(self, market_manager: MCPMarketManager, server_manager: MCPServerManager):
        super().__init__()
        self.market_manager = market_manager
        self.server_manager = server_manager
        self.servers: List[MCPServerInfo] = []
        self.selected_server: Optional[MCPServerInfo] = None
        self.current_category = "all"
        self.search_query = ""
        self._spinner_timer = None
        
        # 添加回调
        self.market_manager.add_status_callback(self._on_status_change)
        # 同时监听启动/停止的状态
        self.server_manager.add_status_callback(self._on_status_change)
        self.market_manager.add_progress_callback(self._on_progress_change)
    
    def compose(self) -> ComposeResult:
        """创建界面布局"""
        yield Header(name="MCP市场")
        
        with Container(id="main-container"):
            with Horizontal(id="top-bar"):
                yield Input(placeholder="搜索MCP服务器...", id="search-input")
                yield Button("搜索", id="search-btn", variant="primary")
                yield Button("刷新", id="refresh-btn")
            
            with Horizontal(id="content-area"):
                # 左侧：分类和服务器列表
                with Vertical(id="left-panel"):
                    yield Label("服务器列表", id="servers-label")
                    yield DataTable(id="servers-table", cursor_type="row")
                    yield Label("分类", id="category-label")
                    yield SelectionList(id="category-list")
                
                # 右侧：服务器详情
                with Vertical(id="right-panel"):
                    yield Label("服务器详情", id="detail-label")
                    with VerticalScroll(id="detail-scroll"):
                        yield Static("选择一个服务器查看详情", id="server-detail")
                    
                    with Horizontal(id="action-buttons"):
                        yield Button("安装", id="install-btn", variant="success")
                        yield Button("卸载", id="uninstall-btn", variant="error")
                        yield Button("启动", id="start-btn", disabled=True, variant="success")
                        yield Button("停止", id="stop-btn", disabled=True, variant="error")
                        yield Button("环境变量", id="env-btn", disabled=True)
                        yield Button("查看工具", id="view-tools-btn")
            
            # 底部：进度条
            yield ProgressBar(id="progress-bar", show_eta=False)
            yield Label("", id="progress-label")
        
        yield Footer()
    
    async def on_mount(self):
        """界面加载完成"""
        servers_table = self.query_one("#servers-table", DataTable)
        servers_table.add_column("名称", key="name")
        servers_table.add_column("描述", key="description")
        servers_table.add_column("版本", key="version")
        servers_table.add_column("状态", key="status")
        servers_table.add_column("评分", key="rating")

        # 初始化分类列表
        await self._load_categories()
        
        # 加载服务器列表
        await self._load_servers()
        
        # 隐藏进度条
        self.query_one("#progress-bar").display = False
        self.query_one("#progress-label").display = False
    
    async def _load_categories(self):
        """加载分类列表"""
        category_list = self.query_one("#category-list", SelectionList)
        
        categories = [
            ("all", "全部"),
            ("utility", "实用工具"),
            ("search", "搜索工具"),
            ("database", "数据库"),
            ("development", "开发工具"),
            ("ai", "AI工具"),
            ("communication", "通信工具"),
            ("media", "媒体工具"),
            ("finance", "金融工具"),
            ("productivity", "生产力"),
            ("other", "其他")
        ]
        
        for category_id, category_name in categories:
            category_list.add_option((category_name, category_id))
        
        # 默认选中"全部"
        category_list.select(0)
    
    async def _load_servers(self, force_refresh: bool = False):
        """加载服务器列表"""
        try:
            # 显示加载状态
            servers_table = self.query_one("#servers-table", DataTable)
            servers_table.clear()
            
            
            # 获取服务器列表
            if self.search_query:
                self.servers = await self.market_manager.search_servers(
                    query=self.search_query,
                    category=None if self.current_category == "all" else self.current_category
                )
            else:
                self.servers = await self.market_manager.get_available_servers(force_refresh)
                
                # 按分类过滤
                if self.current_category != "all":
                    self.servers = [s for s in self.servers if s.category == self.current_category]
            
            # 填充表格
            for server in self.servers:
                # 获取服务器状态
                instance = self.market_manager.get_server_instance(server.name)
                status = self.server_manager.get_server_status(server.name).value
                
                servers_table.add_row(
                    server.display_name,
                    server.description[:50] + "..." if len(server.description) > 50 else server.description,
                    server.version,
                    status,
                    key=server.name
                )
            
        except Exception as e:
            logger.error(f"Failed to load servers: {e}")
            self.notify(f"加载服务器列表失败: {str(e)}", severity="error")
    
    async def on_selection_list_option_selected(self, event: SelectionList.OptionSelected):
        """分类选择变化"""
        if event.selection_list.id == "category-list":
            self.current_category = event.option.value
            await self._load_servers()
    
    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """服务器选择变化"""
        if event.data_table.id == "servers-table":
            # 如果没有行被选中（例如，表格被清空后），row_key可能为None
            if event.row_key is None:
                self.selected_server = None
            else:
                server_name = event.row_key.value
                self.selected_server = next(
                    (s for s in self.servers if s.name == server_name), None
                )
            
            await self._update_server_detail()
    
    async def _update_server_detail(self):
        """更新服务器详情"""
        detail_widget = self.query_one("#server-detail", Static)
        
        if not self.selected_server:
            detail_widget.update("选择一个服务器查看详情")
            return
        
        server = self.selected_server
        
        # 构建详情内容
        detail_content = f"""# {server.display_name}

**版本:** {server.version}  
**分类:** {server.category}  

## 描述
{server.description}

## 标签
{", ".join(server.tags) if server.tags else "无"}

## 安装信息
- **安装类型:** {server.install_type}
- **安装命令:** `{server.install_command}`
- **运行命令:** `{server.run_command}`

## 提供的工具
"""
        
        
        detail_widget.update(Markdown(detail_content))
        
        # 更新按钮状态
        await self._update_action_buttons()
    
    async def _update_action_buttons(self):
        """更新操作按钮状态"""
        install_btn = self.query_one("#install-btn", Button)
        uninstall_btn = self.query_one("#uninstall-btn", Button)
        view_tools_btn = self.query_one("#view-tools-btn", Button)
        start_btn = self.query_one("#start-btn", Button)
        stop_btn = self.query_one("#stop-btn", Button)
        env_btn = self.query_one("#env-btn", Button)
        
        # 如果没有选中服务器，禁用所有按钮
        if not self.selected_server:
            for btn in [install_btn, uninstall_btn, view_tools_btn, start_btn, stop_btn, env_btn]:
                btn.disabled = True
            return

        server_name = self.selected_server.name
        instance = self.market_manager.get_server_instance(server_name)
        status = self.server_manager.get_server_status(server_name)

        # --- 运行相关按钮的逻辑 (这部分逻辑原本就是正确的) ---
        is_running = (status == MCPServerStatus.RUNNING)
        is_startable = status in [MCPServerStatus.STOPPED, MCPServerStatus.INSTALLED, MCPServerStatus.ERROR]
        
        view_tools_btn.disabled = not is_running
        start_btn.disabled = not is_startable
        stop_btn.disabled = not is_running
        env_btn.disabled = not instance # 只要安装了就能编辑环境变量

        # --- 安装/卸载按钮的逻辑 (重构的核心) ---
        if not instance:
            # 状态：从未安装过 (AVAILABLE)
            install_btn.label = "安装"
            install_btn.disabled = False
            uninstall_btn.disabled = True
        else:
            # 状态：已安装、正在运行、停止等
            uninstall_btn.disabled = (status == MCPServerStatus.INSTALLING) # 只有在安装过程中不能卸载

            if status == MCPServerStatus.INSTALLING:
                install_btn.label = "安装中..."
                install_btn.disabled = True
            elif status in [MCPServerStatus.INSTALLED, MCPServerStatus.STOPPED, MCPServerStatus.RUNNING]:
                # 已成功安装，无论运行与否，都显示“已安装”且禁用
                install_btn.label = "已安装"
                if status == MCPServerStatus.RUNNING:
                    install_btn.label = "运行中" # 也可以更具体
                install_btn.disabled = True
            elif status == MCPServerStatus.ERROR:
                # 安装失败，允许重新安装
                install_btn.label = "重新安装"
                install_btn.disabled = False
            else:
                # 兜底情况，理论上不应发生
                install_btn.label = "安装"
                install_btn.disabled = False
    
    async def on_button_pressed(self, event: Button.Pressed):
        """按钮点击事件"""
        server_name = self.selected_server.name
        if not server_name:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        if event.button.id == "search-btn":
            await self._perform_search()
        elif event.button.id == "refresh-btn":
            await self._refresh_servers()
        elif event.button.id == "install-btn":
            await self._install_selected_server()
        elif event.button.id == "uninstall-btn":
            await self._uninstall_selected_server()
        elif event.button.id == "view-tools-btn":
            await self._view_server_tools()
        elif event.button.id == "start-btn":
            self.notify(f"正在启动 {server_name}...", title="MCP Control")
            # 调用是同步的，但它会在后台线程中执行
            self.server_manager.start_server(server_name)
            
        elif event.button.id == "stop-btn":
            self.notify(f"正在停止 {server_name}...", title="MCP Control")
            self.server_manager.stop_server(server_name)
            
        elif event.button.id == "restart-btn":
            self.notify(f"正在重启 {server_name}...", title="MCP Control")
            self.server_manager.restart_server(server_name)
            
        elif event.button.id == "env-btn":
            await self.action_edit_env()

    async def action_edit_env(self) -> None:
        """弹出环境变量编辑器。"""
        if not self.selected_server:
            return
            
        server_instance = self.market_manager.get_server_instance(self.selected_server.name)
        if not server_instance:
            return

        def on_editor_closed(result: Optional[Dict]):
            """This callback is executed when the editor screen is closed."""
            if result is None: # User cancelled
                return

            new_env_vars = result.get("env", {})
            should_restart = result.get("_restart", False)
            
            # Update the instance in the market manager
            server_instance.environment_variables = new_env_vars
            self.market_manager._update_server_instance(server_instance)
            self.notify("环境变量已保存！", severity="success")

            async def maybe_restart():
                """Restart server if requested by user."""
                # We need to refresh the detail panel to show the new state
                await self._update_server_detail() 
                if should_restart and self.server_manager.is_server_running(server_instance.info.name):
                    self.notify(f"正在重启 {server_instance.info.display_name} 以应用环境变量...", title="MCP Control")
                    self.server_manager.restart_server(server_instance.info.name)
            
            self.run_worker(maybe_restart, exclusive=True, group="mcp_restart")

        # Push the editor screen
        self.app.push_screen(
            MCPEnvEditorScreen(server_instance.info.display_name, server_instance.environment_variables),
            on_editor_closed
        )
    
    async def on_input_submitted(self, event: Input.Submitted):
        """输入框提交事件"""
        if event.input.id == "search-input":
            await self._perform_search()
    
    async def _perform_search(self):
        """执行搜索"""
        search_input = self.query_one("#search-input", Input)
        self.search_query = search_input.value.strip()
        await self._load_servers()
    
    async def _refresh_servers(self):
        """刷新服务器列表"""
        await self._load_servers(force_refresh=True)
        self.notify("服务器列表已刷新", severity="information")
    
    async def _install_selected_server(self):
        """安装选中的服务器"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        # 显示进度条
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_label = self.query_one("#progress-label", Label)
        progress_bar.display = True
        progress_label.display = True
        progress_bar.update(progress=0)
        progress_label.update("准备安装...")
        
        try:
            # 执行安装
            success = await self.market_manager.install_server(self.selected_server.name)
            
            if success:
                self.notify(f"服务器 {self.selected_server.display_name} 安装成功", severity="success")
                await self._update_action_buttons()
                await self._load_servers()  # 刷新状态
            else:
                self.notify(f"服务器 {self.selected_server.display_name} 安装失败", severity="error")
        
        except Exception as e:
            logger.error(f"Install error: {e}")
            self.notify(f"安装失败: {str(e)}", severity="error")
        
        finally:
            # 隐藏进度条
            progress_bar.display = False
            progress_label.display = False
    
    async def _uninstall_selected_server(self):
        """卸载选中的服务器"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        
        try:
            success = await self.market_manager.uninstall_server(self.selected_server.name)
            
            if success:
                self.notify(f"服务器 {self.selected_server.display_name} 卸载成功", severity="success")
                await self._update_action_buttons()
                await self._load_servers()  # 刷新状态
            else:
                self.notify(f"服务器 {self.selected_server.display_name} 卸载失败", severity="error")
        
        except Exception as e:
            logger.error(f"Uninstall error: {e}")
            self.notify(f"卸载失败: {str(e)}", severity="error")
    
    async def _view_server_tools(self):
        """查看服务器工具"""
        if not self.selected_server:
            self.notify("请先选择一个服务器", severity="warning")
            return
        server_name = self.selected_server.name

        # 1. First, a sanity check (button should be disabled, but this is safer)
        if not self.server_manager.is_server_running(server_name):
            self.notify(f"服务器 '{server_name}' 未在运行。", title="无法获取工具", severity="warning")
            return

        self.notify(f"正在从 '{server_name}' 获取工具列表...", title="MCP Tools")

        try:
            # 2. Call the manager to get live tool data
            # This is a synchronous call that communicates with the background thread
            tools = self.server_manager.get_server_tools(server_name)

            detail_widget = self.query_one("#server-detail", Static)
            
            if not tools:
                markdown_content = f"""# {self.selected_server.get("display_name")} - 工具

    [dim]服务器 '{server_name}' 当前没有报告任何可用工具。[/dim]
    """
                detail_widget.update(Markdown(markdown_content))
                return

            # 3. Format the tools for display using Rich Markdown
            markdown_content = f"""# {self.selected_server.get("display_name")} - 工具

    [dim]从正在运行的服务器实时获取的工具列表:[/dim]
    ---
    """
            for tool in tools:
                markdown_content += f"### 🛠️ `{tool.name}`\n\n"
                markdown_content += f"{tool.description or '[dim]无描述[/dim]'}\n\n"
                
                schema = tool.input_schema
                if schema and schema.get("properties"):
                    markdown_content += "**参数:**\n"
                    required_params = schema.get("required", [])
                    for param_name, param_info in schema["properties"].items():
                        param_type = param_info.get("type", "any")
                        param_desc = param_info.get("description", "")
                        is_required = " [bold red] (必需)[/bold red]" if param_name in required_params else ""
                        
                        markdown_content += f"- `{param_name}` (`{param_type}`){is_required}: {param_desc}\n"
                else:
                    markdown_content += "[dim]此工具无需参数。[/dim]\n"
                markdown_content += "\n---\n"
            
            # 4. Update the UI
            detail_widget.update(Markdown(markdown_content, code_theme="monokai"))

        except Exception as e:
            logger.error(f"Failed to get tools for {server_name}: {e}")
            self.notify(f"获取工具失败: {e}", severity="error")
        

    
    def _on_status_change(self, server_name: str, status: MCPServerStatus, message: Optional[str] = None):
        """状态变化回调"""
        self.post_message(ServerStatusChanged(server_name, status, message))
    
    def _on_progress_change(self, server_name: str, progress: float, message: str):
        """进度变化回调"""
        self.post_message(ServerInstallProgress(server_name, progress, message))
    
    async def on_server_install_progress(self, event: ServerInstallProgress):
        """处理安装进度消息"""
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_label = self.query_one("#progress-label", Label)
        
        if progress_bar.display:
            progress_bar.update(progress=event.progress * 100)
            progress_label.update(f"{event.server_name}: {event.message}")
    
    async def on_server_status_changed(self, event: ServerStatusChanged):
        """处理状态变化消息"""
        # 刷新服务器列表中的状态
        await self._load_servers()
        
        # 如果是当前选中的服务器，更新按钮状态
        if self.selected_server and self.selected_server.name == event.server_name:
            await self._update_action_buttons()
        
        # 显示通知
        if event.message:
            severity = "success" if event.status in [MCPServerStatus.INSTALLED, MCPServerStatus.RUNNING] else "information"
            if event.status == MCPServerStatus.ERROR:
                severity = "error"
            
            self.notify(f"{event.server_name}: {event.message}", severity=severity)
    
    def action_back(self):
        """返回上一级"""
        self.dismiss()
    
    def action_refresh(self):
        """刷新"""
        asyncio.create_task(self._refresh_servers())
    
    def action_install_selected(self):
        """安装选中的服务器"""
        asyncio.create_task(self._install_selected_server())