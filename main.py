from datetime import datetime
import os
import shlex
import time
import re
from functools import partial
from typing import Any, Dict, Generator, List, Optional, Tuple, Union
import uuid
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.markup import escape
from rich.pretty import pprint
from rich.table import Table

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static, Label
from textual.containers import VerticalScroll, Container, VerticalGroup
from textual.binding import Binding
from rich.spinner import Spinner

from agent.cloud_schemas import CloudTaskUpdate
from agent.task_status import BaseTaskStatus, PlanGenerationEnd, StepExecutionEnd, StepExecutionStart, TaskEnd, ReactAction, ReactThought, ReactObservation, TaskError
from rag.rag_status import AnyRagStatus, BaseRagStatus, RagError, RagSelectionProgress
from snippets.tui_components import SnippetEditorScreen
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
from agent.cli_handler import CLISessionHandler 

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

    def __init__(self, handler: CLISessionHandler):
        super().__init__()
        self.handler = handler
        self._spinner_timer = None
        self.paused_interactive_task: Optional[Generator] = None
        
        self.interaction_state = "NORMAL"  # "NORMAL", "AWAITING_DB_SELECTION", "AWAITING_TABLE_SELECTION"
        self.interaction_context: Dict[str, Any] = {} 
        

    def compose(self) -> ComposeResult:
        """创建应用的UI布局"""
        yield Label("", id="session-label") 
        yield Header(name="DDB-Coding-Agent")
        #with Container(id="header-bar"): # New container for session label
        #    yield Label("", id="session-label")
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
            """[bold gold1]
 _______    ______   __        _______   __    __  ______  __    __  _______          ______    ______   ________  __    __  ________ 
/       \  /      \ /  |      /       \ /  |  /  |/      |/  \  /  |/       \        /      \  /      \ /        |/  \  /  |/        |
$$$$$$$  |/$$$$$$  |$$ |      $$$$$$$  |$$ |  $$ |$$$$$$/ $$  \ $$ |$$$$$$$  |      /$$$$$$  |/$$$$$$  |$$$$$$$$/ $$  \ $$ |$$$$$$$$/ 
$$ |  $$ |$$ |  $$ |$$ |      $$ |__$$ |$$ |__$$ |  $$ |  $$$  \$$ |$$ |__$$ |      $$ |__$$ |$$ | _$$/ $$ |__    $$$  \$$ |   $$ |   
$$ |  $$ |$$ |  $$ |$$ |      $$    $$/ $$    $$ |  $$ |  $$$$  $$ |$$    $$<       $$    $$ |$$ |/    |$$    |   $$$$  $$ |   $$ |   
$$ |  $$ |$$ |  $$ |$$ |      $$$$$$$/  $$$$$$$$ |  $$ |  $$ $$ $$ |$$$$$$$  |      $$$$$$$$ |$$ |$$$$ |$$$$$/    $$ $$ $$ |   $$ |   
$$ |__$$ |$$ \__$$ |$$ |_____ $$ |      $$ |  $$ | _$$ |_ $$ |$$$$ |$$ |__$$ |      $$ |  $$ |$$ \__$$ |$$ |_____ $$ |$$$$ |   $$ |   
$$    $$/ $$    $$/ $$       |$$ |      $$ |  $$ |/ $$   |$$ | $$$ |$$    $$/       $$ |  $$ |$$    $$/ $$       |$$ | $$$ |   $$ |   
$$$$$$$/   $$$$$$/  $$$$$$$$/ $$/       $$/   $$/ $$$$$$/ $$/   $$/ $$$$$$$/        $$/   $$/  $$$$$$/  $$$$$$$$/ $$/   $$/    $$/    
[/bold gold1]\nType `/help` for commands.""",
            border_style="magenta"
        )
        log.write(welcome_panel)
        self.query_one(Input).focus()

        #self.run_worker(self._bootstrap_mcp, exclusive=True, group="mcp_bootstrap", thread=True)
    
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
    def update_session_label(self):
        """Updates the session label in the TUI."""
        session_name = self.handler.get_active_session_name()
        self.query_one("#session-label", Label).update(f"Session: [bold yellow]{escape(session_name)}[/bold yellow]")
   
    def action_new_session(self) -> None:
        """处理快捷键 ctrl+n，开始一个新会话"""
        self.handler.new_session()
        log = self.query_one("#output-log", RichLog)
        log.clear()
        log.write(Panel("[bold green]New session started.[/bold green]", border_style="green"))
        self.update_session_label()

    def action_clear_log(self) -> None:
        """清空屏幕"""
        self.query_one("#output-log").clear()

    def _handle_mode_change_and_resume(self, command: str):
        """
        一个特殊的 worker 函数，用于按顺序执行两件事：
        1. 调用 _handle_command 来切换模式。
        2. 调用 _continue_interactive_task 来恢复暂停的任务。
        这避免了竞态条件。
        """
        # 步骤 1: 处理命令以切换模式
        # 注意：我们调用 _handle_command，它会处理模式切换并打印UI反馈
        self._handle_command(command)
        
        # 步骤 2: 恢复任务
        # 我们只在命令是 /mode ac 时才恢复任务
        cmd_parts = shlex.split(command)
        cmd = cmd_parts[0].lower()
        
        if cmd == '/mode':
            # 确保任务仍然处于暂停状态
            if self.paused_interactive_task:
                resume_signal = f"User confirmed via {cmd_parts[1]} mode"
                self._continue_interactive_task(resume_signal)

    def _handle_cloud_command(self, parts: List[str]):
        """Handles all /cloud subcommands by calling the handler and rendering the result."""

        if len(parts) < 2:
            help_text = """
**Cloud Command Usage**

You need to specify a subcommand. Available options:

- `/cloud login <username> <password>`: Log in to the cloud service.
- `/cloud logout`: Log out from the cloud service.
- `/cloud vms list`: List your cloud environments.
- `/cloud vms create [spec]`: Create a new environment (e.g., `/cloud vms create 2c4g`).
- `/cloud vms delete <environment_id>`
            """
            self._write_to_log(Panel(Markdown(help_text), title="[cyan]Cloud Help[/cyan]", border_style="cyan"))
            # Re-enable input so the user can try again
            self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
            self.call_from_thread(self.query_one(Input).focus)
            return # Exit the function early

        sub_cmd = parts[1].lower()

        if sub_cmd == 'login':
            if len(parts) != 4:
                self._write_to_log(Panel("[bold red]Usage Error:[/bold red] `/cloud login <username> <password>`", border_style="red"))
                self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                self.call_from_thread(self.query_one(Input).focus)
                return

            # 2. Extract username and password.
            username = parts[2]
            password = parts[3]
            
            # 3. Start the background worker to perform the login.
            worker = partial(self._perform_cloud_login, username, password)
            self.run_worker(worker, exclusive=True,thread=True)
            # The worker will re-enable the input box, so we return here.
            return
        
        elif sub_cmd == 'logout':
            message = self.handler.cloud_logout()
            self._write_to_log(Panel(message))
        
        elif sub_cmd == 'vms':
            action = parts[2].lower() if len(parts) > 2 else "list" # default to list

            if action == 'create':
                spec = parts[3] if len(parts) > 3 else "2c4g"
                # The generator now yields data objects, not Panels
                for update in self.handler.cloud_create_vm(spec):
                    self._render_cloud_task_update(update) # Use a dedicated render function
            elif action == 'delete':
                if len(parts) < 4:
                    self._write_to_log(Panel("[bold red]Usage Error:[/bold red] `/cloud vms delete <environment_id>`", border_style="red"))
                else:
                    env_id_to_delete = parts[3]
                    self._write_to_log(Panel(f"Sending request to delete '{env_id_to_delete}'..."))
                    success, message = self.handler.cloud_delete_vm(env_id_to_delete)
                    self._write_to_log(Panel(message, border_style="green" if success else "red"))
                
            else: # 'list'
                try:
                    environments_data = self.handler.cloud_list_vms()
                    if not environments_data:
                        self._write_to_log(Panel("[dim]No cloud environments found.[/dim]", title="Cloud Environments"))
                    else:
                        table = self._format_environments_as_table(environments_data)
                        self._write_to_log(table)
                except Exception as e:
                    self._write_to_log(Panel(f"[red]Error fetching environments: {escape(str(e))}[/red]"))
        else:
            self._write_to_log(Panel(f"[red]Unknown /cloud command: {sub_cmd}[/red]"))

        # Re-enable input for most commands
        self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
        self.call_from_thread(self.query_one(Input).focus)

    def _render_cloud_task_update(self, update: CloudTaskUpdate):
        """Renders a CloudTaskUpdate object into a Rich Panel."""
        if update.status == "IN_PROGRESS":
            self._write_to_log(Panel(f"⏳ {escape(update.message)}"))
        elif update.status == "SUCCESS":
            self._write_to_log(Panel(f"✅ [bold green]{escape(update.message)}[/bold green]", border_style="green"))
        elif update.status == "ERROR":
            self._write_to_log(Panel(f"❌ [bold red]{escape(update.message)}[/bold red]", border_style="red"))
        elif update.status == "FINAL_LIST":
            # The details dict contains the final list to be rendered as a table
            environments = update.details.get("environments", [])
            table = self._format_environments_as_table(environments)
            self._write_to_log(table)

    def _format_environments_as_table(self, environments: List[Dict[str, Any]]) -> Table:
        """Takes a list of environment data and formats it into a Rich Table."""
        table = Table(title="Your Cloud DolphinDB Environments", show_header=True, header_style="bold magenta")
        table.add_column("Name (ID)", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("IP Address", style="green")
        table.add_column("Port")
        table.add_column("Specs (CPU/Mem)")
        table.add_column("Expires In")

        for env in environments:
            status_color = "green" if env['status'] == 'RUNNING' else "yellow"
            expires_dt = datetime.fromisoformat(env['expires_at'])
            now = datetime.utcnow()
            expires_in = expires_dt - now
            if expires_in.total_seconds() < 0:
                expires_str = "[red]Expired[/red]"
            else:
                hours, rem = divmod(int(expires_in.total_seconds()), 3600)
                minutes, _ = divmod(rem, 60)
                expires_str = f"{hours}h {minutes}m"
            
            table.add_row(
                env['id'], Text(env['status'], style=status_color), env.get('public_ip') or "N/A",
                str(env['port']), f"{env['spec_cpu']}c / {env['spec_memory']}G", expires_str
            )
        return table


    def _perform_cloud_login(self, username, password):
        # This worker function is now perfectly aligned with the new architecture.
        # It calls the data-only handler method and then renders the result.
        self._write_to_log(Panel(f"Logging in as {username}..."))
        success, message = self.handler.cloud_login(username, password)
        # The TUI decides how to render the boolean and string into a Panel.
        self._write_to_log(Panel(message, border_style="green" if success else "red"))
        
        self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
        self.call_from_thread(self.query_one(Input).focus)

    # --- Event Handler ---
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """当用户在输入框中按下Enter键时触发"""
        user_input = event.value
        log = self.query_one("#output-log", RichLog)

        if not user_input:
            return
        
        self.query_one(Input).value = ""
        self.query_one(Input).disabled = True

        is_command_only = user_input.lstrip().startswith('/')
        parts = shlex.split(user_input)
        cmd = parts[0].lower() if parts else ""
        
        # 如果是交互式命令的响应，则特殊处理
        if self.interaction_state != "NORMAL":
            if self.interaction_state == "AWAITING_DB_SELECTION":
                self.run_worker(self._handle_db_selection, user_input, exclusive=True, thread=True)
            elif self.interaction_state == "AWAITING_TABLE_SELECTION":
                self.run_worker(self._handle_table_selection, user_input, exclusive=True, thread=True)
        # 如果是暂停任务的响应
        elif self.paused_interactive_task is not None:
             if is_command_only:
                 worker = partial(self._handle_mode_change_and_resume, user_input)
                 self.run_worker(worker, exclusive=True, group="agent_work", thread=True)
             else:
                 worker = partial(self._continue_interactive_task, user_choice=user_input)
                 self.run_worker(worker, exclusive=True, group="agent_work", thread=True)
        # 如果是纯命令
        elif is_command_only:
            worker = partial(self._handle_command, user_input)
            self.run_worker(worker, exclusive=True, thread=True)
        # 否则，视为一个（可能包含@文件引用的）任务
        else:
            worker = partial(self._handle_unified_task, user_input)
            self.run_worker(worker, exclusive=True, thread=True)

    def _handle_unified_task(self, user_input: str):
        """
        统一的任务处理器：先解析和注入文件，再执行主任务。
        """
        self._write_to_log(Panel(f"[bold]>[/bold] {escape(user_input)}", border_style="dim"))
        
        try:
            # --- 阶段一：解析和处理文件 ---
            file_paths = re.findall(r'@([\S]+)', user_input)
            if file_paths:
                spinner_panel = Panel(Spinner("dots", text=" Processing file references..."), 
                                      title="[yellow]Context Preparation[/yellow]", border_style="yellow")
                self._write_to_log(spinner_panel)

                success, message = self.handler.preprocess_and_inject_files(file_paths)
                
                if success:
                    final_panel = Panel(f"[green]✅ Context Ready[/green]\n{escape(message)}", border_style="green")
                else:
                    self._write_to_log(Panel(f"[red]❌ File Error: {escape(message)}[/red]"))
                    self._reset_interaction()
                    return
                self._write_to_log(final_panel)

            # --- 阶段二：执行主任务 ---
            # 简单的路由逻辑：如果包含 'sql', 'database', '查询', '表' 等关键词，则进入 /sql 模式
            # 否则进入 /chat 模式
            sql_keywords = ['sql', 'database', '查询', '表', '数据', 'dolphindb']
            if any(keyword in user_input.lower() for keyword in sql_keywords) and self.handler._get_sql_executor():
                self._execute_interactive_sql_task_with_ui(user_input)

            else:
                self._reset_interaction()
            #else:
                # 暂不处理，只是添加上下文
                # self._handle_chat_task(user_input)

        except Exception as e:
            import traceback
            self._write_to_log(Panel(f"[red]Task failed: {escape(str(e))}\n{traceback.format_exc()}[/red]"))
            self._reset_interaction()

    def _write_to_log(self, content: Any):
        self.call_from_thread(self.query_one("#output-log", RichLog).write, content)

    def _execute_interactive_sql_task_with_ui(self, task_description: str):
        """Worker to START a new interactive task and manage its UI lifecycle."""
        self._write_to_log(Panel(f"[bold blue]Interactive SQL Task:[/bold blue] {escape(task_description)}", title="[bold cyan]Interactive Analyst[/bold cyan]", border_style="cyan"))
        
        try:
            self.paused_interactive_task = self.handler.run_interactive_sql_task(task_description)
            
            for update in self.paused_interactive_task:
                # 如果它返回 False，意味着任务已暂停，我们应该停止迭代并退出 worker
                if not self._process_interactive_update(update):
                    return 

        except StopIteration:
            self.paused_interactive_task = None
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self._write_to_log(Panel(f"[bold red]An unexpected error occurred during the SQL task:[/bold red]\n{tb_str}", border_style="red"))
            self.paused_interactive_task = None
        finally:
            # 只有在任务没有暂停的情况下，才重新启用输入框
            if not self.paused_interactive_task:
                self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                self.call_from_thread(self.query_one(Input).focus)

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
- `/react <your task>`: Use the new, dynamic Reason-Act mode for complex tasks.
---
**Session Management**
- `/session new [name]`: Create and switch to a new session. If name is omitted, a default name is used.
- `/session switch <name>`: Switch to an existing session.
- `/session list`: List all available sessions.
- `/session current`: Show the current active session.
---
**DolphinDB Server**
- `/ddbserver status` (or just `/ddbserver`): Displays the IP address and port of the currently active DolphinDB connection.
- `/ddbserver switch <target>`: Switches the agent's connection to a cloud env
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
**Snippet Management**
- `/snippet new`: Open an editor to create a new snippet.
- `/snippet list`: Show all your saved snippets.
- `/snippet edit <name>`: Open an editor to modify an existing snippet.
- `/snippet delete <name>`: Remove a snippet.
- `/snippet search <query>`: Search snippets by name, description, or tags.
---
**Utility Commands**
- `/save <file_path>`: Save the last successful script from an enhanced task to a file.
- `/stats`: Show execution statistics for the enhanced mode.
- `/new` or `/reset`: Start a new conversation session (or use `Ctrl+N`).
- `/help`: Show this help message.
- `/exit` or `/quit`: Exit the agent (or use `Ctrl+Q`).
                """
                self._write_to_log(Panel(Markdown(help_text), title="[bold cyan]Help[/bold cyan]", border_style="blue"))
            
            elif cmd == '/session':
                self._handle_session_command(parts)
            
            elif cmd == "/cloud":
                self._handle_cloud_command(parts)

            elif cmd == '/ddbserver':
                sub_cmd = parts[1].lower() if len(parts) > 1 else "status" # Default to 'status'
                if sub_cmd == 'switch':
                    if len(parts) < 3:
                        self._write_to_log(Panel("[yellow]Usage: /connections switch <environment_id | local>[/yellow]"))
                    else:
                        conn_name = parts[2]
                        success, message = self.handler.switch_connection(conn_name)
                        self._write_to_log(Panel(message, border_style="green" if success else "red"))
                
                elif sub_cmd == 'status':
                    details = self.handler.get_connection_status()
                    
                    title = f"[cyan]🔌 dolphindb server:[/cyan]"
                    text = (
                        f"- **Host:** {details['host']}\n"
                        f"- **Port:** {details['port']}\n"
                        f"- **User:** {details['user']}"
                    )
                    self._write_to_log(Panel(text, title=title, border_style="cyan"))

                else:
                    self._write_to_log(Panel(f"[red]Unknown connections command: '{sub_cmd}'. Use 'switch' or 'status'.[/red]"))
                
                return 

            elif cmd == '/react':
                if len(parts) > 1:
                    task_description = " ".join(parts[1:])
                    # This worker will now call the new react task handler
                    worker = partial(self._handle_react_task, task_description)
                    self.run_worker(worker, exclusive=True, group="agent_work", thread=True)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a task description for /react.[/yellow]"))
                    self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                    self.call_from_thread(self.query_one(Input).focus)

            elif cmd in ['/exit', '/quit']:
                self.exit()
            
            elif cmd == '/save':
                if len(parts) > 1:
                    file_path = parts[1]
                    success, message = self.handler.save_last_script(file_path)
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

            elif cmd == '/sql':
                if len(parts) > 1:
                    task_description = " ".join(parts[1:])
                    worker = partial(self._execute_interactive_sql_task_with_ui, task_description)
                    self.run_worker(worker, exclusive=True, group="agent_work", thread=True)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a task description for /sql.[/yellow]"))
                    self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                return # Return early to avoid re-enabling input box
            
            elif cmd == '/use':
                # 启动 /use 命令的交互流程
                worker = partial(self._handle_use_command_start, parts)
                self.run_worker(worker, exclusive=True, thread=True)
                return # 提前返回，因为 worker 会管理输入框状态
            
            elif cmd == '/context':
                self._handle_context_command(parts)

            elif cmd == '/mode':
                if len(parts) > 1:
                    new_mode = parts[1].upper()
                    if self.handler.agent_core.set_interactive_mode(new_mode):
                        self._write_to_log(Panel(f"✅ 交互模式已切换到 [bold yellow]{new_mode}[/bold yellow]", border_style="green"))
                    else:
                        self._write_to_log(Panel(f"❌ 无效的模式: '{parts[1]}'. 可用模式: PLAN, ACT", border_style="red"))
                else:
                    current_mode = self.handler.agent_core.get_interactive_mode()
                    self._write_to_log(Panel(f"当前交互模式为: [bold yellow]{current_mode}[/bold yellow]. 使用 `/mode <PLAN|ACT>` 进行切换。", border_style="cyan"))

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
            # This finally block will only execute if the command doesn't pause the agent.
            if not self.paused_interactive_task:
                self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                self.call_from_thread(self.query_one(Input).focus)


    def _handle_use_command_start(self, parts: List[str]):
        """处理 /use 命令的启动，无论是交互式还是直接的。"""
        self._write_to_log(Panel(f"[bold]>[/bold] {escape(' '.join(parts))}", border_style="dim"))

        if len(parts) > 1:
            # 如果有参数，启动直接注入流程
            path = parts[1]
            self._handle_direct_injection(path)
        else:
            # 如果没有参数，启动交互式流程
            self._start_interactive_use_flow()

    def _handle_direct_injection(self, path: str):
        """
        处理直接注入的 worker。
        """
        self._write_to_log(Panel(f"正在尝试添加库表到上下文 `{escape(path)}`...", title="[cyan]添加库表到上下文[/cyan]", border_style="cyan"))

        success, message = self.handler.tui_handle_direct_injection(path)

        if success:
            self._write_to_log(Panel(f"[green]✅ {escape(message)}[/green]"))
        else:
            self._write_to_log(Panel(f"[red]❌ 库表添加失败: {escape(message)}[/red]"))
        
        # 无论成功失败，重置状态并启用输入
        self._reset_interaction()

    def _start_interactive_use_flow(self):
        """
        启动交互式流程 (原 _handle_use_command_start 的逻辑)。
        """
        self.interaction_state = "AWAITING_DB_SELECTION"
        self._write_to_log(Panel("正在获取数据库列表...", title="[cyan]步骤 1/3: 选择数据库[/cyan]", border_style="cyan"))
        
        success, result = self.handler.tui_handle_use_command_start()

        if not success:
            self._write_to_log(Panel(f"[red]错误: {escape(result)}[/red]", border_style="red"))
            self._reset_interaction()
            return

        if not result:
            self._write_to_log(Panel("[yellow]未找到任何数据库。[/yellow]"))
            self._reset_interaction()
            return
        
        self.interaction_context['db_list'] = result

        table = Table(title="可用数据库", show_header=True, header_style="bold magenta")
        table.add_column("编号", style="dim", width=6)
        table.add_column("数据库路径")
        for i, db_path in enumerate(result):
            table.add_row(str(i + 1), db_path)
        
        self._write_to_log(table)
        self.call_from_thread(self.query_one(Input).focus)
        self.call_from_thread(setattr, self.query_one(Input), "placeholder", "请输入数据库编号或完整路径...")
        self.call_from_thread(setattr, self.query_one(Input), "disabled", False)

    def _handle_db_selection(self, user_input: str):
        """处理用户选择数据库的输入。"""
        self._write_to_log(Panel(f"[bold]>[/bold] {escape(user_input)}", border_style="dim"))
        db_list = self.interaction_context.get('db_list', [])
        selected_db = ""

        try:
            # 尝试按编号选择
            choice_idx = int(user_input) - 1
            if 0 <= choice_idx < len(db_list):
                selected_db = db_list[choice_idx]
            else:
                raise ValueError
        except (ValueError, IndexError):
            # 尝试按名称匹配
            if user_input in db_list:
                selected_db = user_input
            else:
                self._write_to_log(Panel("[red]无效的选择。请重新输入。[/red]"))
                self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                self.call_from_thread(self.query_one(Input).focus)
                return
        
        self.interaction_context['selected_db'] = selected_db
        self.interaction_state = "AWAITING_TABLE_SELECTION"

        self._write_to_log(Panel(f"正在获取 `{selected_db}` 下的表...", title="[cyan]步骤 2/3: 选择表[/cyan]", border_style="cyan"))
        
        success, result = self.handler.tui_handle_use_command_db_selected(selected_db)

        if not success:
            self._write_to_log(Panel(f"[red]错误: {escape(result)}[/red]"))
            self._reset_interaction()
            return

        if not result:
            self._write_to_log(Panel(f"[yellow]数据库 `{selected_db}` 下未找到任何表。[/yellow]"))
            self._reset_interaction()
            return

        self.interaction_context['table_list'] = result
        
        table = Table(title=f"'{selected_db}'中的表", show_header=True, header_style="bold magenta")
        table.add_column("编号", style="dim", width=6)
        table.add_column("表名")
        for i, table_name in enumerate(result):
            table.add_row(str(i + 1), table_name)
        
        self._write_to_log(table)
        self.call_from_thread(self.query_one(Input).focus)
        self.call_from_thread(setattr, self.query_one(Input), "placeholder", "请输入表编号或名称 (多个用逗号隔开)...")
        self.call_from_thread(setattr, self.query_one(Input), "disabled", False)

    def _handle_table_selection(self, user_input: str):
        """处理用户选择表的输入。"""
        self._write_to_log(Panel(f"[bold]>[/bold] {escape(user_input)}", border_style="dim"))
        table_list = self.interaction_context.get('table_list', [])
        selected_tables = []
        
        choices = [c.strip() for c in user_input.split(',')]
        
        for choice in choices:
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(table_list):
                    selected_tables.append(table_list[choice_idx])
                else:
                    raise ValueError
            except (ValueError, IndexError):
                if choice in table_list:
                    selected_tables.append(choice)
                else:
                    self._write_to_log(Panel(f"[red]无效的选择: '{escape(choice)}'。请重新输入。[/red]"))
                    self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                    self.call_from_thread(self.query_one(Input).focus)
                    return
        
        if not selected_tables:
            self._write_to_log(Panel("[yellow]您没有选择任何表。操作已取消。[/yellow]"))
            self._reset_interaction()
            return
            
        self._write_to_log(Panel(f"正在为 {len(selected_tables)} 个表注入Schema...", title="[cyan]步骤 3/3: 注入上下文[/cyan]", border_style="cyan"))

        success, result = self.handler.tui_handle_use_command_tables_selected(
            self.interaction_context['selected_db'],
            selected_tables
        )

        if success:
            self._write_to_log(Panel(f"[green]✅ {escape(result)}[/green]"))
        else:
            self._write_to_log(Panel(f"[red]❌ 注入失败: {escape(result)}[/red]"))
        
        self._reset_interaction()

    def _handle_context_command(self, parts: List[str]):
        """处理 /context 命令。"""
        self._write_to_log(Panel(f"[bold]>[/bold] {escape(' '.join(parts))}", border_style="dim"))
        
        sub_cmd = parts[1].lower() if len(parts) > 1 else "show"
        
        if sub_cmd == "show":
            context_str = self.handler.tui_handle_context_show()
            self._write_to_log(Panel(Markdown(context_str), title="[cyan]当前注入的上下文[/cyan]"))
        elif sub_cmd == "clear":
            args = parts[2:]
            message = self.handler.tui_handle_context_clear(args)
            self._write_to_log(Panel(f"[green]✅ {escape(message)}[/green]"))
        else:
            self._write_to_log(Panel("[red]未知命令。用法: /context [show|clear][/red]"))

    def _reset_interaction(self):
        """重置交互状态并重新启用输入框。"""
        self.interaction_state = "NORMAL"
        self.interaction_context = {}
        self.call_from_thread(setattr, self.query_one(Input), "placeholder", "Type your query, /command, or press Ctrl+N for a new session...")
        self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
        self.call_from_thread(self.query_one(Input).focus)

    def _continue_interactive_task(self, user_choice: str):
        """Worker to CONTINUE a paused interactive task."""
        try:
            # --- THIS IS THE CORE FIX ---
            # Step 1: Send the user's choice and get the very first update after resuming.
            update = self.paused_interactive_task.send(user_choice)

            # Step 2: Process that first update. Check if it requests another pause.
            should_continue_loop = self._process_interactive_update(update)
            
            # Step 3: If we are not pausing again, iterate through the rest of the updates.
            if should_continue_loop:
                for subsequent_update in self.paused_interactive_task:
                    if not self._process_interactive_update(subsequent_update):
                        # The task paused again inside the loop, so we exit.
                        return
            # --- END OF CORE FIX ---
        
        except StopIteration:
            self.paused_interactive_task = None
            self._write_to_log(Panel("[dim]Interactive task concluded after user input.[/dim]", border_style="green"))
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self._write_to_log(Panel(f"[bold red]An unexpected error occurred during task continuation:[/bold red]\n{tb_str}", border_style="red"))
            self.paused_interactive_task = None
        finally:
            if not self.paused_interactive_task:
                self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                self.call_from_thread(self.query_one(Input).focus)

    # _process_interactive_update remains the same as it's already correct.
    def _process_interactive_update(self, update: Optional[Dict[str, Any]]) -> bool:
        """
        Processes a single update from the generator. Returns False if paused.
        Now handles potential None update.
        """
        # --- FAILSAFE: Handle NoneType gracefully ---
        if update is None:
            # This can happen if the generator exits right after a send() without yielding anything else.
            # It's a valid, though rare, state. We just continue.
            return True

        if isinstance(update, dict) and update.get("type") == "USER_INTERACTION":
            message = update.get("message", "")
            options = update.get("options", [])
            is_error_prompt = update.get("_is_error_feedback", False)
            panel_title = "[bold red]❓ Error - Awaiting Input[/bold red]" if is_error_prompt else "[yellow]❓ Awaiting Input[/yellow]"
            panel_border = "red" if is_error_prompt else "yellow"
            
            prompt_text = f"{message}\n\n"
            if options: prompt_text += "Options:\n" + "\n".join(f"- {opt}" for opt in options)
            
            self._write_to_log(Panel(Markdown(prompt_text), title=panel_title, border_style=panel_border))
            
            self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
            self.call_from_thread(self.query_one(Input).focus)
            return False # Signal to PAUSE

        elif isinstance(update, ReactThought):
            self._write_to_log(Panel(Markdown(update.thought), title="[cyan]🤔 Thought[/cyan]", border_style="cyan"))
        elif isinstance(update, ReactAction):
            self._write_to_log(Panel(f"[bold]{update.tool_name}[/bold]\nArgs: [code]{escape(str(update.tool_args))}[/code]", title="[yellow]🎬 Action[/yellow]", border_style="yellow"))
        elif isinstance(update, ReactObservation):
            color = "red" if update.is_error else "green"
            self._write_to_log(Panel(escape(update.observation), title=f"[{color}]🔍 Observation[/{color}]", border_style=color))
        elif isinstance(update, (TaskEnd, TaskError)):
            self.paused_interactive_task = None
            color = "green" if isinstance(update, TaskEnd) and update.success else "red"
            title = f"[{color}]🏁 Task Finished[/{color}]" if isinstance(update, TaskEnd) else "[red]💥 Critical Error[/red]"
            final_message = update.final_message if isinstance(update, TaskEnd) else update.message
            self._write_to_log(Panel(Markdown(final_message), title=title, border_style=color))
        
        return True # Signal to CONTINUE

    def _handle_interactive_sql_task(self, task_description: str):
        """Worker to START a new interactive task."""
        self._write_to_log(Panel(f"[bold blue]Interactive SQL Task:[/bold blue] {escape(task_description)}", title="[bold cyan]Interactive Analyst[/bold cyan]", border_style="cyan"))
        
        try:
            self.paused_interactive_task = self.handler.agent_core.run_interactive_sql_task(task_description)
            for update in self.paused_interactive_task:
                if not self._process_interactive_update(update):
                    return # Task paused, worker exits.
        except Exception as e:
            # ... (error handling) ...
            self.paused_interactive_task = None
        finally:
            if not self.paused_interactive_task:
                self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
                self.call_from_thread(self.query_one(Input).focus)

    def _handle_react_task(self, task_description: str):
        """Handles the UI for the new ReAct task execution."""
        self._write_to_log(Panel(
            f"[bold blue]🚀 ReAct Task:[/bold blue] {escape(task_description)}", 
            title="[bold magenta]Dynamic Reason-Act Cycle[/bold magenta]",
            border_style="magenta"
        ))

        try:
            response_generator = self.handler.run_react_task(task_description)
            
            for update in response_generator:
                if isinstance(update, ReactThought):
                    thought_panel = Panel(
                        Markdown(update.thought, code_theme="monokai"),
                        title="[cyan]🤔 Thought[/cyan]",
                        border_style="cyan",
                        padding=(1, 2)
                    )
                    self._write_to_log(thought_panel)
                
                elif isinstance(update, ReactAction):
                    action_text = f"[bold]{update.tool_name}[/bold]\n"
                    action_text += f"Args: [code]{escape(str(update.tool_args))}[/code]"
                    self._write_to_log(Panel(
                        Text.from_markup(action_text),
                        title="[yellow]🎬 Action[/yellow]",
                        border_style="yellow"
                    ))
                
                elif isinstance(update, ReactObservation):
                    color = "red" if update.is_error else "green"
                    title = f"[{color}]🔍 Observation[/{color}]"
                    obs_panel = Panel(
                        escape(update.observation),
                        title=title,
                        border_style=color
                    )
                    self._write_to_log(obs_panel)
                
                elif isinstance(update, TaskEnd):
                    color = "green" if update.success else "red"
                    icon = "✅" if update.success else "❌"
                    final_panel = Panel(
                        Markdown(update.final_message, code_theme="monokai"),
                        title=f"[{color}]{icon} Task Finished[/{color}]",
                        border_style=color
                    )
                    self._write_to_log(final_panel)

                elif isinstance(update, TaskError):
                    self._write_to_log(Panel(
                        f"[bold]Error:[/bold] {escape(update.message)}\n[dim]{escape(update.error_details)}[/dim]",
                        title="[red]💥 Critical Error[/red]",
                        border_style="red"
                    ))

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self._write_to_log(Panel(f"[bold red]An unexpected error occurred during the ReAct task:[/bold red]\n{tb_str}", border_style="red"))
        finally:
            # Re-enable input after the task is done
            self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
            self.call_from_thread(self.query_one(Input).focus)

    def _handle_session_command(self, parts: list[str]):
        """Handles all /session subcommands."""
        if len(parts) < 2:
            self._write_to_log(Panel("Usage: /session <new|switch|list|current>", title="Session Help"))
            return

        sub_cmd = parts[1].lower()

        if sub_cmd == 'new':
            session_name = " ".join(parts[2:]) if len(parts) > 2 else None
            self.handler.new_session(session_name)
            self.query_one("#output-log").clear()
            self._write_to_log(Panel(f"Switched to new session: '{self.handler.get_active_session_name()}'", border_style="green"))
            self.call_from_thread(self.update_session_label)
        
        elif sub_cmd == 'switch':
            if len(parts) < 3:
                self._write_to_log(Panel("[yellow]Usage: /session switch <session_name>[/yellow]"))
                return
            session_name = " ".join(parts[2:])
            if session_name in  [session['id'] for session in self.handler.list_sessions()]:
                self.handler.switch_session(session_name)
                self.query_one("#output-log").clear()
                self._write_to_log(Panel(f"Switched to session: '{session_name}'", border_style="green"))
                self.call_from_thread(self.update_session_label)
            else:
                self._write_to_log(Panel(f"[red]Session '{escape(session_name)}' not found.[/red]"))

        elif sub_cmd == 'list':
            sessions = self.handler.list_sessions()
            active_session = self.handler.get_active_session_name()
            if not sessions:
                self._write_to_log(Panel("No sessions found.", title="Sessions"))
                return
            
            list_text = ""
            for s in sorted(sessions, key=lambda x: x["id"]):
                if s == active_session:
                    list_text += f"- [bold yellow]{s} (active)[/bold yellow]\n"
                else:
                    list_text += f"- {s}\n"
            self._write_to_log(Panel(Markdown(list_text), title="Available Sessions"))
        
        elif sub_cmd == 'current':
            self._write_to_log(Panel(f"The current active session is: [bold yellow]{self.handler.get_active_session_name()}[/bold yellow]"))

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
        snippet_manager = self.handler.agent_core.snippet_manager

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
            
            self._write_to_log(Panel(list_text, title="Your Snippets"))

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
            if self.handler.agent_core.mcp_market_manager:
                self.call_from_thread(self.push_screen, MCPMarketScreen(self.handler.agent_core.mcp_market_manager, self.handler.agent_core.mcp_server_manager))
            else:
                self._write_to_log(Panel("[red]MCP市场管理器未初始化[/red]", border_style="red"))
        
        elif sub_cmd == 'manager':
            if self.handler.agent_core.mcp_market_manager and self.handler.agent_core.mcp_server_manager:
                self.call_from_thread(self.push_screen, MCPManagerScreen(self.handler.agent_core.mcp_server_manager, self.handler.agent_core.mcp_market_manager))
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
        if not self.handler.agent_core.mcp_market_manager:
            self._write_to_log(Panel("[red]MCP市场管理器未初始化[/red]", border_style="red"))
            return
        
        try:
            installed_servers = self.handler.agent_core.mcp_market_manager.get_installed_servers()
            
            if not installed_servers:
                self._write_to_log(Panel("没有已安装的MCP服务器。使用 `/mcp market` 浏览和安装服务器。", title="MCP服务器"))
                return
            
            list_text = "## 已安装的MCP服务器\n\n"
            for server in installed_servers:
                status = self.handler.agent_core.mcp_server_manager.get_server_status(server.info.name) if self.handler.agent_core.mcp_server_manager else server.status
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
        if not self.handler.agent_core.mcp_server_manager:
            self._write_to_log(Panel("[red]MCP服务器管理器未初始化[/red]", border_style="red"))
            return
        
        try:
            all_tools = self.handler.agent_core.mcp_server_manager.get_all_tools()
            
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
        if not self.handler.agent_core.mcp_market_manager:
            self._write_to_log(Panel("[red]MCP市场管理器未初始化[/red]", border_style="red"))
            return
        
        def install_server_sync():
            async def do_install():
                try:
                    self._write_to_log(Panel(f"正在安装MCP服务器: {escape(server_name)}...", border_style="yellow"))
                    success = await self.handler.agent_core.mcp_market_manager.install_server(server_name)
                    
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
            response_generator = self.handler.run_chat_task(user_input)

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

        # 从 .env 获取默认模型配置名称
        default_model_name = os.getenv("Default_LLM_Model", "deepseek")

        # 验证默认模型配置是否存在
        model_config = ModelManager.get_model_config(default_model_name)
        if not model_config:
            raise ValueError(
                f"Default model configuration '{default_model_name}' not found in models.json. "
                f"Please check your Default_LLM_Model environment variable."
            )

        mcp_market_manager = MCPMarketManager()
        mcp_server_manager = MCPServerManager(mcp_market_manager)

        #mcp_server_manager.bootstrap_builtin_servers()

        cli_handler = CLISessionHandler(
            project_path=project_path,
            model_name=default_model_name,  # 使用配置名称（如 "deepseek"），而非实际模型名
            max_window_size=model_config.max_context_tokens or 64000,
            mcp_market_manager = mcp_market_manager,
            mcp_server_manager = mcp_server_manager
        )
        
        app = DDBAgentApp(handler=cli_handler)
        app.run()

    except Exception as e:
        print(f"Failed to initialize or run the agent: {e}")
        import traceback
        traceback.print_exc()