import os
import shlex
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
from textual.containers import VerticalScroll
from textual.binding import Binding

from utils.logger import setup_llm_logger
from agent.agent import DDBAgent
from llm.llm_client import LLMResponse
from llm.models import ModelManager


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

    def compose(self) -> ComposeResult:
        """创建应用的UI布局"""
        yield Header(name="DDB-Coding-Agent")
        with VerticalScroll(id="output-container"):
            yield RichLog(id="output-log", wrap=False, highlight=True, markup=True)
        yield Input(placeholder="Type your query, /command, or press Ctrl+N for a new session...", id="input-box")
        yield Footer()

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

        log.write(Panel(escape(user_input), title="You", border_style="blue", title_align="right"))
        self.query_one(Input).value = ""

        self.query_one(Input).disabled = True

        # --- 关键修改在这里 ---
        # 使用 functools.partial 来包装带参数的 worker 函数
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

- Type your query directly to chat with the agent (RAG-based Q&A).
- Use the following slash commands for special actions:
  - `/chat <your query>`: Explicitly start a RAG-based chat query.
  - `/code <your task>`: Ask the agent to write and execute DolphinDB code.
  - `/save <file_path>`: Save the last successful script to a file.
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
                    # 将 /chat 后面的所有部分作为查询内容
                    query = " ".join(parts[1:])
                    # 直接调用处理普通聊天任务的 worker
                    print("query:",query)
                    self._handle_chat_task(query)
                    # 因为 _handle_chat_task 自己会处理 finally, 这里我们就不需要再处理了
                    # 但是为了让外层的 try...finally 正常工作，我们需要 return
                    return
                else:
                    self._write_to_log(Panel("[yellow]Please provide a query after /chat.[/yellow]", border_style="yellow"))


            elif cmd == '/code':
                if len(parts) > 1:
                    task_description = " ".join(parts[1:])
                    self._handle_code_task(task_description)
                else:
                    self._write_to_log(Panel("[yellow]Please provide a task description.[/yellow]", border_style="yellow"))
            
            else:
                self._write_to_log(Panel(f"[red]Unknown command: {cmd}[/red]", border_style="red"))
        
        finally:
            self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
            self.call_from_thread(self.query_one(Input).focus)

    def _handle_chat_task(self, user_input: str):
        """在后台处理普通聊天，并流式输出结果 (Static Widget 修复版)"""

        # 为这次任务的 Static widget 生成一个唯一的ID
        task_widget_id = f"task-static-{uuid.uuid4()}"
        
        # 在内存中创建一个 Panel 对象，我们将在循环中更新它
        assistant_panel = Panel("...", title="Agent", border_style="yellow", title_align="left")
        
        # 标记是否已经将 Static widget 写入 log
        is_widget_mounted = False

        try:
            response_generator = self.agent.run_task(user_input, stream=True)
            full_response = ""
            
            for part in response_generator:
                if isinstance(part, str):
                    # 只有在收到第一个 token 时，才创建并写入 Static widget
                    if not is_widget_mounted:
                        assistant_panel.border_style = "green"
                        # 创建一个包含 Panel 的 Static widget，并赋予其唯一ID
                        static_widget = Static(assistant_panel, id=task_widget_id)
                        
                        # 将这个 Static widget 写入 RichLog
                        self.call_from_thread(self.query_one("#output-log").write, static_widget)
                        is_widget_mounted = True
                    
                    full_response += part
                    
                    # 更新 Panel 的内容
                    assistant_panel.renderable = Markdown(full_response, code_theme="monokai")
                    
                    # 定义一个在主线程中执行的更新函数
                    def update_ui():
                        try:
                            # 通过ID查询到UI中的 Static widget
                            widget_to_update = self.query_one(f"#{task_widget_id}", Static)
                            # 调用 Static widget 的 update 方法，传入更新后的 Panel
                            widget_to_update.update(assistant_panel)
                        except Exception:
                            pass
                    
                    # 从后台线程调用这个UI更新函数
                    self.call_from_thread(update_ui)

                elif isinstance(part, LLMResponse) and not part.success:
                    error_message = f"[bold red]Error:[/bold red]\n{escape(part.error_message)}"
                    if is_widget_mounted:
                        def update_error_ui():
                            try:
                                widget_to_update = self.query_one(f"#{task_widget_id}", Static)
                                assistant_panel.renderable = error_message
                                assistant_panel.border_style = "red"
                                widget_to_update.update(assistant_panel)
                            except Exception:
                                pass
                        self.call_from_thread(update_error_ui)
                    else:
                        self._write_to_log(Panel(error_message, title="Agent", border_style="red", title_align="left"))
                    break
        
        except Exception as e:
            error_message = f"[bold red]An unexpected error occurred:[/bold red]\n{escape(str(e))}"
            if 'is_widget_mounted' in locals() and is_widget_mounted:
                 def update_critical_error_ui():
                    try:
                        widget_to_update = self.query_one(f"#{task_widget_id}", Static)
                        assistant_panel.renderable = error_message
                        assistant_panel.border_style = "red"
                        widget_to_update.update(assistant_panel)
                    except Exception:
                        pass
                 self.call_from_thread(update_critical_error_ui)
            else:
                 self._write_to_log(Panel(error_message, title="Agent", border_style="red", title_align="left"))

        finally:
            self.call_from_thread(setattr, self.query_one(Input), "disabled", False)
            self.call_from_thread(self.query_one(Input).focus)

    def _handle_code_task(self, task_description: str):
        self._write_to_log(Panel(f"[bold blue]Received coding task:[/bold blue] {escape(task_description)}", title="[bold magenta]Coding Task[/bold magenta]"))
        
        try:
            response_generator = self.agent.run_coding_task_with_planner(task_description)
            
            for update in response_generator:
                update_type = update.get("type")
                message = escape(update.get("message", ""))

                if update_type == "status":
                    self._write_to_log(Panel(f"⚙️ {message}", border_style="yellow"))
                
                elif update_type == "plan":
                    plan_text = ""
                    plan_data = update.get("plan", [])
                    if isinstance(plan_data, list):
                        for i, step in enumerate(plan_data):
                            action = escape(str(step.get("action", "N/A")))
                            thought = escape(str(step.get("thought", "No thought.")))
                            plan_text += f"[b]{i+1}. {action}[/b]\n   [dim]Thought: {thought}[/dim]\n"
                    self._write_to_log(Panel(plan_text, title="[yellow]Execution Plan[/yellow]", border_style="yellow"))
                
                elif update_type == "step_start":
                    step_num = update.get('step', '?')
                    action = escape(str(update.get("action", "N/A")))
                    thought = escape(str(update.get("thought", "")))
                    log_entry = f"[bold green]▶️ Step {step_num}: {action}[/bold green]\n[dim]   Thought: {thought}[/dim]"
                    self._write_to_log(Panel(log_entry, title=f"Step {step_num} Start", border_style="green"))

                elif update_type == "step_result":
                    observation = update.get('observation', '')
                    obs_renderable = escape(observation)
                    self._write_to_log(Panel(obs_renderable, title="[cyan]Observation[/cyan]", border_style="cyan"))

                elif update_type == "final_result":
                    final_exec_result = update.get('result_object')
                    self._write_to_log(Panel(
                        "[bold green]✅ Task Completed Successfully![/bold green]",
                        title="[bold green]Success[/bold green]",
                        border_style="green"
                    ))
                    if final_exec_result and final_exec_result.executed_script:
                        self._write_to_log(Panel(
                            Syntax(final_exec_result.executed_script, "dos", theme="monokai", line_numbers=True),
                            title="[yellow]Final Successful Script[/yellow]", border_style="yellow"
                        ))
                    if final_exec_result and final_exec_result.data is not None:
                        result_str = str(final_exec_result.data)
                        self._write_to_log(Panel(result_str, title="[cyan]Result Data[/cyan]", border_style="cyan"))

                elif update_type == "error":
                    self._write_to_log(Panel(
                        f"[bold red]❌ Task Failed.[/bold red]\n\n[bold]Final Error:[/bold]\n{escape(update.get('message', 'Unknown error.'))}",
                        title="[bold red]Failure[/bold red]",
                        border_style="red"
                    ))
        except Exception as e:
            self._write_to_log(Panel(f"[bold red]An unexpected error occurred during the coding task:[/bold red]\n{e}", border_style="red"))
        
if __name__ == "__main__":
    try:
        project_path = os.path.dirname(os.path.abspath(__file__))
        log_dir = ".ddb_agent/logs"
        os.makedirs(log_dir, exist_ok=True)
        setup_llm_logger(log_file_path=os.path.join(log_dir, "llm_requests.log"))

        ModelManager.load_models()

        ddb_agent = DDBAgent(
            project_path=project_path,
            model_name="deepseek-chat",
            max_window_size=64000
        )

        app = DDBAgentApp(agent=ddb_agent)
        app.run()

    except Exception as e:
        print(f"Failed to initialize or run the agent: {e}")
        import traceback
        traceback.print_exc()