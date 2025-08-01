import os
import shlex
import time
from functools import partial
from typing import Any, Dict, Generator, Tuple, Union
import uuid
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.markup import escape
from rich.pretty import pprint

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.containers import VerticalScroll, Container, VerticalGroup
from textual.binding import Binding
from rich.spinner import Spinner

from agent.task_status import BaseTaskStatus, PlanGenerationEnd, StepExecutionEnd, StepExecutionStart, TaskEnd
from rag.rag_status import AnyRagStatus, BaseRagStatus, RagError, RagSelectionProgress
from snippets.tui_components import SnippetEditorScreen
from utils.logger import setup_llm_logger
from agent.agent import DDBAgent
from llm.llm_client import LLMResponse, StreamChunk
from llm.models import ModelManager

from textual.message import Message

from agent.enhanced_executor_status import (
    AnyExecutorStatus, ExecutorStatusUpdate, TaskExecutionStart, PlanGenerationStart,
    PlanGenerationEnd, StepExecutionStart, StepExecutionEnd, ExecutorError,
    RecoveryPlanStart, RecoveryPlanEnd, TaskExecutionEnd, FinalScriptExtracted
)

# MCP相关导入
#try:
from mcp.ui.mcp_market_screen import MCPMarketScreen
from mcp.ui.mcp_manager_screen import MCPManagerScreen
from mcp.market.market_manager import MCPMarketManager
from mcp.server.server_manager import MCPServerManager
MCP_AVAILABLE = True
#except ImportError:
   # MCP_AVAILABLE = False
class StartSpinner(Message):
    """请求开始一个 Spinner 动画的消息。"""
    def __init__(self, widget_id: str) -> None:
        self.widget_id = widget_id
        super().__init__()

class StopSpinner(Message):
    """请求停止 Spinner 动画的消息。"""
    pass
class DDBAgentApp(App):
    """一个基于 Textual 的高级 DolphinDB Agent TUI"""

    CSS_PATH = "ddb_agent.css"
    BINDINGS = [
        Binding("ctrl+n", "new_session", "New Session", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_log", "Clear Log", show=True),
    ]

    def __init__(self, agent: DDBAgent):
        super().__init__()
        self.agent = agent
        self._spinner_timer = None
        
        # 初始化MCP组件
        self.mcp_market_manager = agent.get_mcp_market_manager()
        self.mcp_server_manager = agent.get_mcp_server_manager()
        

    def compose(self) -> ComposeResult:
        """创建应用的UI布局"""
        yield Header(name="DDB-Coding-Agent")
        with VerticalScroll(id="output-container"):
            yield RichLog(id="output-log", wrap=False, highlight=True, markup=True)
        yield Input(placeholder="Type your query, /command, or press Ctrl+N for a new session...", id="input-box")
        yield Footer()

    async def _bootstrap_mcp(self):
        """在后台工作线程中执行MCP内置服务器的引导过程。"""
        if self.mcp_server_manager:
            self._write_to_log(Panel("🚀 [dim]正在自动安装和加载内置 MCP 服务器...[/dim]", border_style="yellow"))
            self.mcp_server_manager.bootstrap_builtin_servers()
            self._write_to_log(Panel("✅ [dim]内置 MCP 服务器加载完成。[/dim]", border_style="green"))


    def on_mount(self) -> None:
        """应用加载完成时调用，用于初始化"""
        log = self.query_one("#output-log", RichLog)
        welcome_panel = Panel(
            "[bold green]Welcome to the DDB-Coding-Agent![/bold green]\nType `/help` for commands.",
            title="[bold magenta]DDB Agent[/bold magenta]",
            border_style="magenta"
        )
        log.write(welcome_panel)
        self.query_one(Input).focus()

        self.run_worker(self._bootstrap_mcp, exclusive=True, group="mcp_bootstrap", thread=True)
    
    def on_start_spinner(self, message: StartSpinner) -> None:
        """在主线程中处理 StartSpinner 消息。"""
        try:
            widget_to_refresh = self.query_one(f"#{message.widget_id}")
            if self._spinner_timer is not None:
                self._spinner_timer.stop() # 先停止旧的，以防万一
            
            self._spinner_timer = self.set_interval(
                1 / 15, 
                widget_to_refresh.refresh, 
                name="spinner_updater"
            )
        except Exception:
            # 如果 widget 找不到，就不做任何事
            pass

    def on_stop_spinner(self, message: StopSpinner) -> None:
        """在主线程中处理 StopSpinner 消息。"""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    # --- Action Handlers (for BINDINGS) ---
    def action_new_session(self) -> None:
        """处理快捷键 ctrl+n，开始一个新会话"""
        self.agent.start_new_session()
        log = self.query_one("#output-log", RichLog)
        log.clear()
        log.write(Panel("[bold green]New session started.[/bold green]", border_style="green"))

    def action_clear_log(self) -> None:
        """清空屏幕"""
        self.query_one("#output-log").clear()

    # --- Event Handler ---
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """当用户在输入框中按下Enter键时触发"""
        user_input = event.value
        log = self.query_one("#output-log", RichLog)

        if not user_input:
            return
        
        self.query_one(Input).value = ""
        self.query_one(Input).disabled = True

        if user_input.lower().startswith('/'):
            worker = partial(self._handle_command, user_input)
            self.run_worker(worker, exclusive=True, group="agent_work", thread=True)
        else:
            worker = partial(self._handle_chat_task, user_input)
            self.run_worker(worker, exclusive=True, group="agent_work", thread=True)

    def _write_to_log(self, content: Any):
        self.call_from_thread(self.query_one("#output-log", RichLog).write, content)

    def _handle_command(self, command: str):
        try:
            parts = shlex.split(command)
            cmd = parts[0].lower()
            
            if cmd == '/help':
                help_text = """
**DDB-Coding-Agent Help**
---
**Core Modes**
- Type your query directly to chat with the agent (RAG-based Q&A).
- `/chat <your query>`: Explicitly start a RAG-based chat query.
- `/code <your task>`: Ask the agent to write and execute DolphinDB code (basic mode).
- `/enhanced <your task>`: Use enhanced plan-and-execute mode for complex tasks.
- `/spec <your task>`: Enter structured spec development mode (EARS methodology).

---
**Snippet Management**
- `/snippet new`: Open an editor to create a new snippet.
- `/snippet list`: Show all your saved snippets.
- `/snippet edit <name>`: Open an editor to modify an existing snippet.
- `/snippet delete <name>`: Remove a snippet.
- `/snippet search <query>`: Search snippets by name, description, or tags.
---
**MCP (Model Context Protocol) Commands**
- `/mcp market`: Open MCP market to browse and install MCP servers.
- `/mcp manager`: Open MCP server management interface.
- `/mcp list`: List all installed MCP servers and their status.
- `/mcp start <server_name>`: Start a specific MCP server.
- `/mcp stop <server_name>`: Stop a specific MCP server.
- `/mcp tools`: List all available MCP tools.
- `/mcp install <server_name>`: Install an MCP server from the market.
---
**Utility Commands**
- `/save <file_path>`: Save the last successful script from an enhanced task to a file.
- `/stats`: Show execution statistics for the enhanced mode.
- `/new` or `/reset`: Start a new conversation session (or use `Ctrl+N`).
- `/help`: Show this help message.
- `/exit` or `/quit`: Exit the agent (or use `Ctrl+Q`).
                """
                self._write_to_log(Panel(Markdown(help_text), title="[bold cyan]Help[/bold cyan]", border_style="blue"))
            
            elif cmd in ['/new', '/reset']:
                self.action_new_session()

            elif cmd in ['/exit', '/quit']:
                self.exit()
            
            elif cmd == '/save':
                if len(parts) > 1:
                    file_path = parts[1]
                    success, message = self.agent.save_last_script(file_path)
                    style = "green" if success else "red"
                    self._write_to_log(Panel(f"{'✅' if success else '❌'} {message}", border_style=style))
                else:
                    self._write_to_log(Panel("[yellow]Please provide a file path.[/yellow]", border_style="yellow"))

            elif cmd == '/chat':
                if len(parts) > 1:
                    query = " ".join(parts[1:])
                    self._handle_chat_task(query)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a query after /chat.[/yellow]", border_style="yellow"))
                    self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                    self.call_from_thread(self.query_one(Input).focus)


            elif cmd == '/code':
                if len(parts) > 1:
                    task_description = " ".join(parts[1:])
                    self._handle_code_task(task_description)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a task description.[/yellow]", border_style="yellow"))
            
            elif cmd == '/enhanced':
                if len(parts) > 1:
                    task_description = " ".join(parts[1:])
                    self._handle_enhanced_code_task(task_description)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a task description.[/yellow]", border_style="yellow"))

            elif cmd == '/snippet':
                self._handle_snippet_command(parts)
            
            elif cmd == '/mcp':
                self._handle_mcp_command(parts)
            
            elif cmd == '/spec':
                if len(parts) > 1:
                    task_description = " ".join(parts[1:])
                    self._handle_spec_task(task_description)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a task description for spec mode.[/yellow]", border_style="yellow"))
            
            elif cmd == '/stats':
                stats = self.agent.enhanced_executor.get_execution_stats()
                stats_text = f"""
**Enhanced Executor Statistics**

- Total Tasks: {stats.get('total_tasks', 0)}
- Successful Tasks: {stats.get('successful_tasks', 0)}
- Failed Tasks: {stats.get('failed_tasks', 0)}
- Success Rate: {stats.get('success_rate', 0):.1%}
- Total Steps: {stats.get('total_steps', 0)}
- Failed Steps: {stats.get('failed_steps', 0)}
- Step Failure Rate: {stats.get('step_failure_rate', 0):.1%}
- Recovery Attempts: {stats.get('recovery_attempts', 0)}
                """
                self._write_to_log(Panel(Markdown(stats_text), title="[bold cyan]Statistics[/bold cyan]", border_style="cyan"))
            
            else:
                self._write_to_log(Panel(f"[red]Unknown command: {cmd}[/red]", border_style="red"))
        
        finally:
            self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
            self.call_from_thread(self.query_one(Input).focus)

    def _handle_snippet_command(self, parts: list[str]):
        """Handles all /snippet subcommands."""
        if len(parts) < 2:
            help_text = """
**Snippet Command Usage**
- `/snippet new`: Create a new snippet.
- `/snippet list`: List all your snippets.
- `/snippet search <query>`: Search for snippets.
- `/snippet edit <name>`: Edit an existing snippet.
- `/snippet delete <name>`: Delete a snippet.
            """
            self._write_to_log(Panel(Markdown(help_text), title="[cyan]Snippet Help[/cyan]"))
            return

        sub_cmd = parts[1].lower()
        snippet_manager = self.agent.snippet_manager

        if sub_cmd == 'new':
            self.call_from_thread(self.push_screen, SnippetEditorScreen(snippet_manager))
        
        elif sub_cmd == 'list':
            all_snippets = snippet_manager.get_all_snippets()
            if not all_snippets:
                self._write_to_log(Panel("You don't have any snippets yet. Use `/snippet new` to create one.", title="Snippets"))
                return
            
            list_text = ""
            for s in all_snippets:
                list_text += f"- [bold cyan]{s.name}[/bold cyan]: {escape(s.description or 'No description.')}\n"
            self._write_to_log(Panel(Markdown(list_text), title="Your Snippets"))

        elif sub_cmd == 'edit':
            if len(parts) < 3:
                self._write_to_log(Panel("[yellow]Usage: /snippet edit <snippet_name>[/yellow]"))
                return
            snippet_name = parts[2]
            snippet_to_edit = snippet_manager.get_snippet(snippet_name)
            if snippet_to_edit:
                self.call_from_thread(
                    self.push_screen, 
                    SnippetEditorScreen(snippet_manager, snippet_to_edit=snippet_to_edit)
                )
            else:
                self._write_to_log(Panel(f"[red]Snippet '{escape(snippet_name)}' not found.[/red]"))

    def _handle_mcp_command(self, parts: list[str]):
        """处理MCP相关命令"""
        if not MCP_AVAILABLE:
            self._write_to_log(Panel("[red]MCP功能不可用。请检查MCP模块是否正确安装。[/red]", border_style="red"))
            return
        
        if len(parts) < 2:
            help_text = """
**MCP Command Usage**
- `/mcp market`: Open MCP market to browse and install servers.
- `/mcp manager`: Open MCP server management interface.
- `/mcp list`: List all installed MCP servers and their status.
- `/mcp start <server_name>`: Start a specific MCP server.
- `/mcp stop <server_name>`: Stop a specific MCP server.
- `/mcp tools`: List all available MCP tools.
- `/mcp install <server_name>`: Install an MCP server from the market.
            """
            self._write_to_log(Panel(Markdown(help_text), title="[cyan]MCP Help[/cyan]"))
            return

        sub_cmd = parts[1].lower()

        if sub_cmd == 'market':
            if self.mcp_market_manager:
                self.call_from_thread(self.push_screen, MCPMarketScreen(self.mcp_market_manager))
            else:
                self._write_to_log(Panel("[red]MCP市场管理器未初始化[/red]", border_style="red"))
        
        elif sub_cmd == 'manager':
            if self.mcp_market_manager and self.mcp_server_manager:
                self.call_from_thread(self.push_screen, MCPManagerScreen(self.mcp_server_manager, self.mcp_market_manager))
            else:
                self._write_to_log(Panel("[red]MCP管理器未初始化[/red]", border_style="red"))
        
        elif sub_cmd == 'list':
            self._handle_mcp_list()
        
        elif sub_cmd == 'start':
            if len(parts) < 3:
                self._write_to_log(Panel("[yellow]Usage: /mcp start <server_name>[/yellow]"))
                return
            server_name = parts[2]
            self._handle_mcp_start(server_name)
        
        elif sub_cmd == 'stop':
            if len(parts) < 3:
                self._write_to_log(Panel("[yellow]Usage: /mcp stop <server_name>[/yellow]"))
                return
            server_name = parts[2]
            self._handle_mcp_stop(server_name)
        
        elif sub_cmd == 'tools':
            self._handle_mcp_tools()
        
        elif sub_cmd == 'install':
            if len(parts) < 3:
                self._write_to_log(Panel("[yellow]Usage: /mcp install <server_name>[/yellow]"))
                return
            server_name = parts[2]
            self._handle_mcp_install(server_name)
        
        else:
            self._write_to_log(Panel(f"[red]Unknown MCP command: {sub_cmd}[/red]", border_style="red"))

    def _handle_mcp_list(self):
        """列出所有已安装的MCP服务器"""
        if not self.mcp_market_manager:
            self._write_to_log(Panel("[red]MCP市场管理器未初始化[/red]", border_style="red"))
            return
        
        try:
            installed_servers = self.mcp_market_manager.get_installed_servers()
            
            if not installed_servers:
                self._write_to_log(Panel("没有已安装的MCP服务器。使用 `/mcp market` 浏览和安装服务器。", title="MCP服务器"))
                return
            
            list_text = "## 已安装的MCP服务器\n\n"
            for server in installed_servers:
                status = self.mcp_server_manager.get_server_status(server.info.name) if self.mcp_server_manager else server.status
                status_emoji = {
                    "running": "🟢",
                    "stopped": "🔴", 
                    "installed": "🟡",
                    "error": "❌",
                    "installing": "🔄"
                }.get(status.value, "❓")
                
                list_text += f"- **{server.info.display_name}** {status_emoji} ({status.value})\n"
                list_text += f"  - 版本: {server.info.version}\n"
                list_text += f"  - 描述: {server.info.description}\n"
                if server.process_id:
                    list_text += f"  - 进程ID: {server.process_id}\n"
                list_text += "\n"
            
            self._write_to_log(Panel(Markdown(list_text), title="[cyan]MCP服务器列表[/cyan]"))
            
        except Exception as e:
            self._write_to_log(Panel(f"[red]获取服务器列表失败: {str(e)}[/red]", border_style="red"))

    def _handle_mcp_start(self, server_name: str):
        """启动MCP服务器"""
        if not self.mcp_server_manager:
            self._write_to_log(Panel("[red]MCP服务器管理器未初始化[/red]", border_style="red"))
            return
        
        def start_server_sync():
            try:
                self._write_to_log(Panel(f"正在启动MCP服务器: {escape(server_name)}...", border_style="yellow"))
                
                success = self.mcp_server_manager.start_server(server_name)
                
                
                if success:
                    self._write_to_log(Panel(f"✅ 已发送启动 '{escape(server_name)}' 的请求。请关注状态变化。", border_style="green"))
                else:
                    self._write_to_log(Panel(f"❌ 发送启动 '{escape(server_name)}' 的请求失败。", border_style="red"))
            except Exception as e:
                self._write_to_log(Panel(f"❌ 启动命令执行出错: {str(e)}", border_style="red"))
        
        start_server_sync()

    def _handle_mcp_stop(self, server_name: str):
        """停止MCP服务器"""
        if not self.mcp_server_manager:
            self._write_to_log(Panel("[red]MCP服务器管理器未初始化[/red]", border_style="red"))
            return
        
        def stop_server_sync():
            try:
                self._write_to_log(Panel(f"正在停止MCP服务器: {escape(server_name)}...", border_style="yellow"))
                success = self.mcp_server_manager.stop_server(server_name)
                
                if success:
                     self._write_to_log(Panel(f"✅ 已发送停止 '{escape(server_name)}' 的请求。", border_style="green"))
                else:
                    self._write_to_log(Panel(f"❌ 发送停止 '{escape(server_name)}' 的请求失败。", border_style="red"))
            except Exception as e:
                self._write_to_log(Panel(f"❌ 停止命令执行出错: {str(e)}", border_style="red"))
        

        stop_server_sync()

    def _handle_mcp_tools(self):
        """列出所有可用的MCP工具"""
        if not self.mcp_server_manager:
            self._write_to_log(Panel("[red]MCP服务器管理器未初始化[/red]", border_style="red"))
            return
        
        try:
            all_tools = self.mcp_server_manager.get_all_tools()
            
            if not all_tools:
                self._write_to_log(Panel("没有可用的MCP工具。请先启动一些MCP服务器。", title="MCP工具"))
                return
            
            tools_text = "## 可用的MCP工具\n\n"
            current_server = None
            
            for tool in all_tools:
                if tool.server_name != current_server:
                    current_server = tool.server_name
                    tools_text += f"### 来自 {current_server}\n\n"
                
                tools_text += f"- **{tool.name}**: {tool.description}\n"
            
            self._write_to_log(Panel(Markdown(tools_text), title="[cyan]MCP工具列表[/cyan]"))
            
        except Exception as e:
            self._write_to_log(Panel(f"[red]获取工具列表失败: {str(e)}[/red]", border_style="red"))

    def _handle_mcp_install(self, server_name: str):
        """安装MCP服务器"""
        if not self.mcp_market_manager:
            self._write_to_log(Panel("[red]MCP市场管理器未初始化[/red]", border_style="red"))
            return
        
        def install_server_sync():
            async def do_install():
                try:
                    self._write_to_log(Panel(f"正在安装MCP服务器: {escape(server_name)}...", border_style="yellow"))
                    success = await self.mcp_market_manager.install_server(server_name)
                    
                    if success:
                        self._write_to_log(Panel(f"✅ MCP服务器 {escape(server_name)} 安装成功", border_style="green"))
                    else:
                        self._write_to_log(Panel(f"❌ MCP服务器 {escape(server_name)} 安装失败", border_style="red"))
                except Exception as e:
                    self._write_to_log(Panel(f"❌ 安装失败: {str(e)}", border_style="red"))

            # 在同步函数中运行异步代码
            import asyncio
            asyncio.run(do_install())
            
        install_server_sync()

    def _handle_chat_task(self, user_input: str):
        """
        处理聊天任务，并在 Agent 响应期间将用户问题置于标题栏。
        将最终结果写入 RichLog，并移除临时 widget。
        """
        streaming_widget_id = f"streaming-static-{uuid.uuid4()}"
        output_container = self.query_one("#output-container")
        log = self.query_one("#output-log")

        # 模糊历史记录
        self.call_from_thread(log.add_class, "defocused")

        # --- 动态创建 Widget 子类 ---
        class StreamingStatic(Static):
            """一个在尺寸变化时能自动滚动父容器的 Static Widget。"""
            def on_resize(self, event) -> None:
                # 当这个 widget 的高度因为内容更新而改变时，这个方法会被调用。
                # 这是确保滚动到底部的最可靠时机。
                self.parent.scroll_end(animate=False)
            
        spinner = Spinner("dots", text=" 发送请求...")
        truncated_query = escape(user_input[:70] + '...' if len(user_input) > 70 else user_input)
        context_title = f"You👨💻 [dim]: {truncated_query}[/dim]"
        assistant_panel = Panel(spinner, title=context_title, border_style="yellow", title_align="left")
        
        # 使用我们自定义的 StreamingStatic 类来创建 widget
        streaming_widget = StreamingStatic(assistant_panel, id=streaming_widget_id)

        # 挂载临时 widget
        self.call_from_thread(output_container.mount, streaming_widget)

        self.post_message(StartSpinner(streaming_widget_id))
        
        final_renderable = None
        
        # 跟踪状态的变量
        reasoning_content = ""
        full_response = ""
        in_reasoning_phase = False
        in_content_phase = False

        try:
            response_generator = self.agent.run_task(user_input)

            try:
                while True:
                    part = next(response_generator)

                    def update_ui(new_renderable):
                        """线程安全的UI更新函数"""
                        try:
                            widget_to_update = self.query_one(f"#{streaming_widget_id}", Static)
                            widget_to_update.update(new_renderable)
                        except Exception:
                            pass # Widget 可能已被移除

                    if isinstance(part, BaseRagStatus):
                        # 如果是RAG状态，只更新Spinner的文本
                        spinner.text = f" {part.message}"
                        
                        # 如果RAG出错，改变边框颜色并保持Spinner
                        if isinstance(part, RagError):
                            assistant_panel.border_style = "red"
                        
                        self.call_from_thread(update_ui, assistant_panel)

                    elif isinstance(part, StreamChunk):
                        if part.type == "reasoning":
                            if not in_reasoning_phase:
                                self.post_message(StopSpinner())
                                assistant_panel.border_style = "cyan" # 思考时用青色
                                assistant_panel.title = "🌊 Agent is thinking..."
                                in_reasoning_phase = True
                            reasoning_content += part.data
                            assistant_panel.renderable = Markdown(reasoning_content, code_theme="monokai", style="dim cyan")
                           
                        elif part.type == "content":
                            if not in_content_phase:
                                assistant_panel.border_style = "green" # 内容时用绿色
                                assistant_panel.title = "🐬 Assistant"
                                in_content_phase = True

                            full_response += part.data
                            
                            # 根据是否有推理内容来决定显示方式
                            if reasoning_content:
                                from rich.console import Group
                                from rich.panel import Panel as RichPanel
                                from rich.rule import Rule
                                
                                # 创建推理部分的小面板
                                reasoning_section = RichPanel(
                                    Markdown(reasoning_content, code_theme="monokai", style="dim cyan"),
                                    title="[dim]🌊 Reasoning[/dim]",
                                    border_style="grey50",
                                    padding=(0, 1)
                                )
                                
                                # 创建响应内容
                                response_markdown = Markdown(full_response, code_theme="monokai") if full_response else Text("")
                                
                                # 使用Group组合内容，用Rule作为分隔线
                                combined_content = Group(
                                    reasoning_section,
                                    Rule(style="grey50"),  # 分隔线
                                    response_markdown
                                )
                                
                                assistant_panel.renderable = combined_content
                            else:
                                # 如果没有思考过程，直接显示内容
                                assistant_panel.renderable = Markdown(full_response, code_theme="monokai")
                            
                        else:
                            raise Exception(f"Unexpected chunk type: {part.type}")
                        
                        def update_ui():
                            try:
                                widget_to_update = self.query_one(f"#{streaming_widget_id}", Static)
                                # 只需更新内容，滚动将由 on_resize 事件自动处理
                                widget_to_update.update(assistant_panel)
                            except Exception:
                                pass
                        
                        self.call_from_thread(update_ui)

                    else:
                        raise Exception(f"Unexpected chunk type: {type(part)}")
                        
            except StopIteration as e:
                final_result = e.value

                if isinstance(final_result, LLMResponse) and not final_result.success:
                    self.post_message(StopSpinner())
                    error_message = f"[bold red]Error:[/bold red]\n{escape(final_result.error_message)}"
                    final_renderable = Panel(error_message, title="Agent", border_style="red", title_align="left")
            
            if final_renderable is None:
                # 构建最终的渲染内容
                if reasoning_content and full_response:
                    from rich.console import Group
                    from rich.panel import Panel as RichPanel
                    from rich.rule import Rule
                    
                    # 创建推理部分的小面板
                    reasoning_section = RichPanel(
                        Markdown(reasoning_content, code_theme="monokai"),
                        title="[dim]🌊 Reasoning[/dim]",
                        border_style="grey50",
                        padding=(0, 1)
                    )
                    
                    # 创建响应内容
                    response_markdown = Markdown(full_response, code_theme="monokai", inline_code_theme="monokai")
                    
                    # 使用Group组合内容
                    combined_content = Group(
                        reasoning_section,
                        Rule(style="grey50"),
                        response_markdown
                    )
                    
                    final_renderable = Panel(
                        combined_content,
                        title="Agent",
                        border_style="green",
                        title_align="left"
                    )
                else:
                    # 只有内容或只有推理
                    content_to_show = full_response if full_response else reasoning_content
                    response_markdown = Markdown(content_to_show, code_theme="monokai", inline_code_theme="monokai") if content_to_show else Text("Empty response.")
                    final_renderable = Panel(
                        response_markdown,
                        title="Agent",
                        border_style="green",
                        title_align="left"
                    )

        except Exception as e:
            self.post_message(StopSpinner())
            import traceback
            tb_str = traceback.format_exc()
            error_message = f"[bold red]An unexpected error occurred:[/bold red]\n{escape(str(e))}\n\n[dim]{escape(tb_str)}[/dim]"
            final_renderable = Panel(error_message, title="Agent", border_style="red", title_align="left")

        finally:
            self.post_message(StopSpinner())
            def cleanup_and_finalize():
                try:
                    widget_to_remove = self.query_one(f"#{streaming_widget_id}")
                    widget_to_remove.remove()
                except Exception:
                    pass

                #移除 'defocused' 类，恢复历史记录
                log.remove_class("defocused")
                
                user_panel = Panel(escape(user_input), title="You", border_style="blue", title_align="right")
                log.write(user_panel)

                if final_renderable:
                    log.write(final_renderable)

                self.query_one(Input).disabled = False
                self.query_one(Input).focus()
                
                output_container.scroll_end(animate=True, duration=0.2)

            self.call_from_thread(cleanup_and_finalize)
    
    def _handle_code_task(self, task_description: str):
        """
        处理增强的代码任务，采用与 /chat 类似的用户界面逻辑。
        所有更新都发生在一个动态的 Panel 中。
        """
        streaming_widget_id = f"task-static-{uuid.uuid4()}"
        output_container = self.query_one("#output-container")
        log = self.query_one("#output-log")

        # 1. 准备UI
        self.call_from_thread(log.add_class, "defocused")

        class StreamingStatic(Static):
            """一个在尺寸变化时能自动滚动父容器的 Static Widget。"""
            def on_resize(self, event) -> None:
                self.parent.scroll_end(animate=False)
        
        # 创建一个初始的、包含任务描述的Panel
        initial_content = f"[bold]任务目标:[/bold]\n{escape(task_description)}"
        assistant_panel = Panel(
            initial_content,
            title="[yellow]🟡 任务准备中...[/yellow]",
            border_style="yellow",
            title_align="left"
        )
        
        streaming_widget = StreamingStatic(assistant_panel, id=streaming_widget_id)
        self.call_from_thread(output_container.mount, streaming_widget)

        

        # --- 用于构建最终Panel内容的变量 ---
        # 我们将把所有步骤的详细信息收集起来
        detail_logs = []
        
        in_reasoning_phase = False
        in_content_phase = False
        reasoning_content = ""
        full_response = ""
        try:
            response_generator = self.agent.run_coding_task(task_description)
            from rich.console import Group
            for update in response_generator:
                # --- A. 处理任务状态更新 (BaseTaskStatus) ---
                if isinstance(update, BaseTaskStatus):
                    # 更新Panel的标题来反映当前宏观状态
                    assistant_panel.title = f"[cyan]⚙️ {escape(update.message)}[/cyan]"
                    
                    # 只有在步骤结束或计划生成时，才将详细信息添加到日志列表中
                    if isinstance(update, PlanGenerationEnd):
                        plan_text = ""
                        for i, step in enumerate(update.plan):
                            action = escape(str(step.get("action", "N/A")))
                            thought = escape(str(step.get("thought", "No thought.")))
                            plan_text += f"[b]{i+1}. {action}[/b]\n   [dim]Thought: {thought}[/dim]\n"
                        detail_logs.append(Panel(plan_text, title="📋 执行计划", border_style="yellow"))

                    elif isinstance(update, StepExecutionEnd):
                        obs_renderable = escape(update.observation)
                        status_icon = "✅" if update.is_success else "❌"
                        border_color = "green" if update.is_success else "red"
                        title = f"{status_icon} 步骤 {update.step_index} 结果"
                        
                        content_group = []
                        # if update.script:
                        #     content_group.append(Syntax(update.script, "dos", theme="monokai", line_numbers=True, word_wrap=True))
                        content_group.append(Text.from_markup(obs_renderable))
                        detail_logs.append(Panel(Group(*content_group), title=title, border_style=border_color))

                    elif isinstance(update, TaskEnd):
                        # 任务结束时，更新标题为最终状态
                        final_border = "green" if update.success else "red"
                        final_title = "✅ 任务成功完成" if update.success else "❌ 任务失败"
                        assistant_panel.title = f"[{final_border}]{final_title}[/{final_border}]"
                        assistant_panel.border_style = final_border
                        
                        # 添加最终消息到日志
                        final_content_group = [Text.from_markup(escape(update.final_message))]
                        if update.final_message:
                             final_content_group.append(Panel(Syntax(update.final_script, "dos", theme="monokai", line_numbers=True), title="📜 最终脚本"))
                        detail_logs.append(Group(*final_content_group))

                    # 每次收到状态更新后，重新渲染整个Panel
                    # Panel的内容是所有累积的详细日志
                    assistant_panel.renderable = Group(*detail_logs)
                    


                elif isinstance(update, StreamChunk):
                    if update.type == "reasoning":
                        if not in_reasoning_phase:
                            self.post_message(StopSpinner())
                            assistant_panel.border_style = "cyan"
                            assistant_panel.title = "🌊 Agent is thinking..."
                            in_reasoning_phase = True
                        reasoning_content += update.data
                        assistant_panel.renderable = Markdown(reasoning_content, code_theme="monokai", style="dim cyan")
                    elif update.type == "content":
                        if not in_content_phase:
                            in_content_phase = True
                            assistant_panel.border_style = "green"
                            assistant_panel.title = "🐬 Assistant"
                        full_response += update.data

                        if reasoning_content:
                            from rich.console import Group
                            from rich.panel import Panel as RichPanel
                            from rich.rule import Rule
                                
                            # 创建推理部分的小面板
                            reasoning_section = RichPanel(
                                Markdown(reasoning_content, code_theme="monokai", style="dim cyan"),
                                title="[dim]🌊 Reasoning[/dim]",
                                border_style="grey50",
                                padding=(0, 1)
                            )
                                
                            # 创建响应内容
                            response_markdown = Markdown(full_response, code_theme="monokai") if full_response else Text("")
                                
                            # 使用Group组合内容，用Rule作为分隔线
                            combined_content = Group(
                                reasoning_section,
                                Rule(style="grey50"),  # 分隔线
                                response_markdown
                            )
                                
                            assistant_panel.renderable = combined_content
                        else:
                            assistant_panel.renderable = Markdown(full_response, code_theme="monokai")
                
                def update_ui():
                    """线程安全的UI更新函数"""
                    try:
                        widget_to_update = self.query_one(f"#{streaming_widget_id}", Static)
                        # 只需更新内容，滚动将由 on_resize 事件自动处理
                        widget_to_update.update(assistant_panel)
                    except Exception:
                        pass
                        
                self.call_from_thread(update_ui)

        except Exception as e:
            # 错误处理
            assistant_panel.title = "[red]💥 执行错误[/red]"
            assistant_panel.border_style = "red"
            assistant_panel.renderable = Text(f"任务执行出错: {str(e)}")
            self.call_from_thread(update_ui)
        
        finally:
            # --- 任务结束，固化整个容器内容到永久日志 ---
            def cleanup_and_finalize():
                final_renderable = None
                try:
                    # 获取 assistant_panel 的最终状态作为要固化的内容
                    final_renderable = assistant_panel
                    # 移除临时 widget
                    widget_to_remove = self.query_one(f"#{streaming_widget_id}")
                    widget_to_remove.remove()
                except Exception:
                    pass
                
                log.remove_class("defocused")

                user_panel = Panel(escape(task_description), title="You", border_style="blue", title_align="right")
                
                # 我们不再需要 agent_final_panel，因为 final_renderable 就是最终的 Panel
                log.write(user_panel)
                if final_renderable:
                    log.write(final_renderable)

                self.query_one(Input).disabled = False
                self.query_one(Input).focus()
                log.scroll_end(animate=True)

            self.call_from_thread(cleanup_and_finalize)

    def _handle_spec_task(self, task_description: str):
        """处理规范开发模式任务"""
        self._write_to_log(Panel(
            f"[bold blue]🔍 Structured Spec Development:[/bold blue] {escape(task_description)}", 
            title="[bold cyan]EARS Spec Development Mode[/bold cyan]",
            border_style="cyan"
        ))
        
        try:
            response_generator = self.agent.run_spec_task(task_description)
            
            for update in response_generator:
                update_type = update.get("type")
                message = escape(update.get("message", ""))
                
                if update_type == "status":
                    self._write_to_log(Panel(f"⚙️ {message}", border_style="yellow"))
                
                elif update_type == "requirements_document":
                    content = update.get("content", "")
                    file_path = update.get("file_path", "")
                    self._write_to_log(Panel(
                        Markdown(content, code_theme="monokai", inline_code_theme="monokai"),
                        title="[bold cyan]📋 需求文档 (Requirements Document)[/bold cyan]",
                        border_style="cyan"
                    ))
                    self._write_to_log(Panel(
                        f"[dim]📁 文档已保存到: {escape(file_path)}[/dim]",
                        border_style="cyan"
                    ))
                
                elif update_type == "design_document":
                    content = update.get("content", "")
                    file_path = update.get("file_path", "")
                    self._write_to_log(Panel(
                        Markdown(content, code_theme="monokai", inline_code_theme="monokai"),
                        title="[bold blue]🏗️ 技术方案设计 (Technical Design)[/bold blue]",
                        border_style="blue"
                    ))
                    self._write_to_log(Panel(
                        f"[dim]📁 文档已保存到: {escape(file_path)}[/dim]",
                        border_style="blue"
                    ))
                
                elif update_type == "tasks_document":
                    content = update.get("content", "")
                    file_path = update.get("file_path", "")
                    self._write_to_log(Panel(
                        Markdown(content, code_theme="monokai", inline_code_theme="monokai"),
                        title="[bold green]📝 实施计划 (Implementation Tasks)[/bold green]",
                        border_style="green"
                    ))
                    self._write_to_log(Panel(
                        f"[dim]📁 文档已保存到: {escape(file_path)}[/dim]",
                        border_style="green"
                    ))
                
                elif update_type == "confirmation_request":
                    phase = update.get("phase", "")
                    phase_names = {
                        "requirements": "需求确认",
                        "design": "设计确认", 
                        "tasks": "任务确认"
                    }
                    phase_name = phase_names.get(phase, phase)
                    
                    self._write_to_log(Panel(
                        f"⏸️ [bold yellow]{phase_name}[/bold yellow]\n\n{message}",
                        title="[bold yellow]⏸️ 等待确认 (Awaiting Confirmation)[/bold yellow]",
                        border_style="yellow"
                    ))
                
                elif update_type == "final_result":
                    success = update.get("success", False)
                    spec_name = update.get("spec_name", "")
                    requirements_path = update.get("requirements_path", "")
                    design_path = update.get("design_path", "")
                    tasks_path = update.get("tasks_path", "")
                    
                    if success:
                        summary_text = f"""[bold green]✅ 规范开发工作流程完成！[/bold green]

📂 **规范名称:** {escape(spec_name)}

📋 **需求文档:** {escape(requirements_path)}
🏗️ **技术设计:** {escape(design_path)}  
📝 **实施计划:** {escape(tasks_path)}

[dim]所有文档已保存到 specs 目录，您现在可以开始实施任务。[/dim]"""
                        
                        self._write_to_log(Panel(
                            summary_text,
                            title="[bold green]🎉 规范开发完成 (Spec Development Complete)[/bold green]",
                            border_style="green"
                        ))
                    else:
                        error_text = f"[bold red]❌ 规范开发失败[/bold red]\n\n{message}"
                        self._write_to_log(Panel(
                            error_text,
                            title="[bold red]失败 (Failed)[/bold red]",
                            border_style="red"
                        ))
                
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self._write_to_log(Panel(
                f"[bold red]规范开发过程中发生意外错误:[/bold red]\n{e}\n\n[dim]{escape(tb_str)}[/dim]",
                border_style="red"
            ))
    
    def _handle_enhanced_code_task(self, task_description: str):
        """处理增强的代码任务"""
        self._write_to_log(Panel(
            f"[bold blue]🚀 Enhanced Coding Task:[/bold blue] {escape(task_description)}", 
            title="[bold magenta]Enhanced Plan & Execute[/bold magenta]",
            border_style="magenta"
        ))
        
        try:
            response_generator = self.agent.run_enhanced_coding_task(task_description)
            
            for update in response_generator:
                if isinstance(update, ExecutorStatusUpdate):
                    self._write_to_log(Panel(f"⚙️ {escape(update.message)}", border_style="yellow"))

                elif isinstance(update, PlanGenerationEnd):
                    plan_text = ""
                    plan_data = update.plan.steps
                 

                    
                    for step in plan_data:
                        action = escape(str(step.action))
                        thought = escape(str(step.thought))
                        args = step.args
                        
                        plan_text += f"[b]{step.step_id}. {action}[/b]\n"
                        plan_text += f"   [dim]💭 {thought}[/dim]\n"
                        if args:
                            plan_text += f"   [dim]📋 Args: {escape(str(args))}[/dim]\n"
                        plan_text += "\n"
                    
                    self._write_to_log(Panel(plan_text, title="[yellow]📋 Execution Plan[/yellow]", border_style="yellow"))

                elif isinstance(update, StepExecutionStart):
                    step = update.step
                    log_entry = f"[bold green]▶️ Step {step.step_id}: {escape(step.action)}[/bold green]\n[dim]   💭 {escape(step.thought)}[/dim]"
                    self._write_to_log(Panel(log_entry, title=f"Step {step.step_id} Start", border_style="green"))

                elif isinstance(update, StepExecutionEnd):
                    step = update.step
                    result = update.result
                    success = result.success
                    observation = str(result.data) if success else result.error_message
                    if observation is None: 
                        observation = ""
                    status_icon = "✅" if success else "❌"
                    status_color = "green" if success else "red"
                    
                    obs_text = f"{status_icon} [bold]Result:[/bold]\n{escape(observation)}"
                    if update.execution_time:
                        obs_text += f"\n\n[dim]⏱️ Execution time: {update.execution_time:.2f}s[/dim]"
                    
                    self._write_to_log(Panel(obs_text, title=f"[{status_color}]Step {step.step_id} Result[/{status_color}]", border_style=status_color))

                elif isinstance(update, RecoveryPlanEnd):
                    recovery_text = f"[bold yellow]🔧 Recovery for Step {update.new_plan.steps[0].dependencies[0] if update.new_plan.steps and update.new_plan.steps[0].dependencies else '?'}[/bold yellow]\n\n"
                    for step in update.new_plan.steps:
                         if step.status == "pending": # Only show new steps
                            action = escape(str(step.action))
                            thought = escape(str(step.thought))
                            recovery_text += f"[b]{step.step_id}. {action}[/b]\n   [dim]💭 {thought}[/dim]\n"
                    
                    self._write_to_log(Panel(recovery_text, title="[yellow]🔄 Recovery Plan[/yellow]", border_style="yellow"))

                elif isinstance(update, TaskExecutionEnd):
                    stats = update.stats
                    if update.success:
                        success_text = f"[bold green]✅ Enhanced Task Completed Successfully![/bold green]\n\n"
                        success_text += f"[dim]⏱️ Total execution time: {update.execution_time:.2f}s[/dim]\n"
                        success_text += f"[dim]📊 Steps executed: {stats.get('total_steps', 0)}[/dim]"
                        self._write_to_log(Panel(success_text, title="[bold green]🎉 Success[/bold green]", border_style="green"))
                        
                        if update.final_result and update.final_result.data is not None:
                            result_str = str(update.final_result.data)
                            self._write_to_log(Panel(result_str, title="[cyan]📊 Result Data[/cyan]", border_style="cyan"))
                    else:
                        error_text = f"[bold red]❌ Enhanced Task Failed[/bold red]\n\n"
                        error_text += f"[bold]Reason:[/bold] {escape(update.message)}\n\n"
                        error_text += f"[dim]📊 Steps attempted: {stats.get('total_steps', 0)}[/dim]\n"
                        error_text += f"[dim]🔄 Recovery attempts: {stats.get('recovery_attempts', 0)}[/dim]"
                        self._write_to_log(Panel(error_text, title="[bold red]💥 Failure[/bold red]", border_style="red"))

                elif isinstance(update, FinalScriptExtracted):
                    script_content = update.script
                    self._write_to_log(Panel(
                        Syntax(script_content, "dos", theme="monokai", line_numbers=True, word_wrap=True),
                        title="[yellow]📜 Final Successful Script[/yellow]",
                        border_style="yellow"
                    ))
                
                elif isinstance(update, ExecutorError):
                    error_text = f"[bold red]💥 Execution Error[/bold red]\n\n"
                    error_text += f"[bold]Message:[/bold] {escape(update.message)}\n"
                    if update.step:
                         error_text += f"[bold]Failed Step:[/bold] {update.step.step_id}\n"
                    error_text += f"[dim]Details: {escape(update.error_details)}[/dim]"
                    self._write_to_log(Panel(error_text, title="[bold red]Error[/bold red]", border_style="red"))

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self._write_to_log(Panel(f"[bold red]An unexpected error occurred during the enhanced coding task:[/bold red]\n{tb_str}\n{e}", border_style="red"))

            
if __name__ == "__main__":
    try:
        project_path = os.path.dirname(os.path.abspath(__file__))
        log_dir = ".ddb_agent/logs"
        os.makedirs(log_dir, exist_ok=True)
        #setup_llm_logger(log_file_path=os.path.join(log_dir, "llm_requests.log"))

        ModelManager.load_models()

        mcp_market_manager = MCPMarketManager()
        mcp_server_manager = MCPServerManager(mcp_market_manager)
        
        ddb_agent = DDBAgent(
            project_path=project_path,
            model_name="deepseek-chat",
            max_window_size=64000,
            mcp_market_manager = mcp_market_manager,
            mcp_server_manager = mcp_server_manager
        )

        app = DDBAgentApp(agent=ddb_agent)
        app.run()

    except Exception as e:
        print(f"Failed to initialize or run the agent: {e}")
        import traceback
        traceback.print_exc()