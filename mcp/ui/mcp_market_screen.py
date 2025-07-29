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

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Input, Button, Static, DataTable, 
    SelectionList, Label, Tabs, TabPane, ProgressBar
)
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.message import Message

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
    
    def __init__(self, market_manager: MCPMarketManager):
        super().__init__()
        self.market_manager = market_manager
        self.servers: List[MCPServerInfo] = []
        self.selected_server: Optional[MCPServerInfo] = None
        self.current_category = "all"
        self.search_query = ""
        
        # 添加回调
        self.market_manager.add_status_callback(self._on_status_change)
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
                    yield Label("分类", id="category-label")
                    yield SelectionList(id="category-list")
                    
                    yield Label("服务器列表", id="servers-label")
                    yield DataTable(id="servers-table")
                
                # 右侧：服务器详情
                with Vertical(id="right-panel"):
                    yield Label("服务器详情", id="detail-label")
                    with VerticalScroll(id="detail-scroll"):
                        yield Static("选择一个服务器查看详情", id="server-detail")
                    
                    with Horizontal(id="action-buttons"):
                        yield Button("安装", id="install-btn", variant="success")
                        yield Button("卸载", id="uninstall-btn", variant="error")
                        yield Button("查看工具", id="view-tools-btn")
            
            # 底部：进度条
            yield ProgressBar(id="progress-bar", show_eta=False)
            yield Label("", id="progress-label")
        
        yield Footer()
    
    async def on_mount(self):
        """界面加载完成"""
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
            servers_table.add_column("名称", key="name")
            servers_table.add_column("描述", key="description")
            servers_table.add_column("版本", key="version")
            servers_table.add_column("状态", key="status")
            servers_table.add_column("评分", key="rating")
            
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
                status = instance.status.value if instance else "available"
                
                servers_table.add_row(
                    server.display_name,
                    server.description[:50] + "..." if len(server.description) > 50 else server.description,
                    server.version,
                    status,
                    f"{server.rating:.1f}",
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
            server_name = event.row_key.value
            self.selected_server = next((s for s in self.servers if s.name == server_name), None)
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
**作者:** {server.author}  
**分类:** {server.category}  
**许可证:** {server.license or "未知"}

## 描述
{server.description}

## 标签
{", ".join(server.tags) if server.tags else "无"}

## 统计信息
- **下载量:** {server.downloads:,}
- **评分:** {server.rating:.1f}/5.0

## 安装信息
- **安装类型:** {server.install_type}
- **安装命令:** `{server.install_command}`
- **运行命令:** `{server.run_command}`

## 提供的工具
"""
        
        if server.tools:
            for tool in server.tools:
                detail_content += f"- **{tool['name']}**: {tool.get('description', '无描述')}\n"
        else:
            detail_content += "无工具信息\n"
        
        if server.homepage:
            detail_content += f"\n[主页]({server.homepage})"
        
        if server.repository:
            detail_content += f" | [代码仓库]({server.repository})"
        
        detail_widget.update(Markdown(detail_content))
        
        # 更新按钮状态
        await self._update_action_buttons()
    
    async def _update_action_buttons(self):
        """更新操作按钮状态"""
        if not self.selected_server:
            return
        
        install_btn = self.query_one("#install-btn", Button)
        uninstall_btn = self.query_one("#uninstall-btn", Button)
        
        # 获取服务器状态
        instance = self.market_manager.get_server_instance(self.selected_server.name)
        
        if instance:
            if instance.status == MCPServerStatus.INSTALLED:
                install_btn.disabled = True
                install_btn.label = "已安装"
                uninstall_btn.disabled = False
            elif instance.status == MCPServerStatus.INSTALLING:
                install_btn.disabled = True
                install_btn.label = "安装中..."
                uninstall_btn.disabled = True
            elif instance.status == MCPServerStatus.RUNNING:
                install_btn.disabled = True
                install_btn.label = "运行中"
                uninstall_btn.disabled = False
            elif instance.status == MCPServerStatus.ERROR:
                install_btn.disabled = False
                install_btn.label = "重新安装"
                uninstall_btn.disabled = False
            else:
                install_btn.disabled = False
                install_btn.label = "安装"
                uninstall_btn.disabled = True
        else:
            install_btn.disabled = False
            install_btn.label = "安装"
            uninstall_btn.disabled = True
    
    async def on_button_pressed(self, event: Button.Pressed):
        """按钮点击事件"""
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
        
        # 这里可以打开一个新的界面显示工具详情
        tools_info = "## 工具列表\n\n"
        
        for tool in self.selected_server.tools:
            tools_info += f"### {tool['name']}\n"
            tools_info += f"{tool.get('description', '无描述')}\n\n"
            
            if 'input_schema' in tool:
                schema = tool['input_schema']
                if 'properties' in schema:
                    tools_info += "**参数:**\n"
                    for param_name, param_info in schema['properties'].items():
                        param_type = param_info.get('type', 'unknown')
                        param_desc = param_info.get('description', '')
                        tools_info += f"- `{param_name}` ({param_type}): {param_desc}\n"
                    tools_info += "\n"
        
        # 更新详情面板
        detail_widget = self.query_one("#server-detail", Static)
        detail_widget.update(Markdown(tools_info))
    
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