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
from textual.containers import VerticalScroll
from textual.binding import Binding
from rich.spinner import Spinner

from utils.logger import setup_llm_logger
from agent.agent import DDBAgent
from llm.llm_client import LLMResponse
from llm.models import ModelManager

from textual.message import Message
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

- Type your query directly to chat with the agent (RAG-based Q&A).
- Use the following slash commands for special actions:
  - `/chat <your query>`: Explicitly start a RAG-based chat query.
  - `/code <your task>`: Ask the agent to write and execute DolphinDB code (basic mode).
  - `/enhanced <your task>`: Use enhanced plan-and-execute mode with advanced tools.
  - `/spec <your task>`: Enter spec development mode for iterative code development.
  - `/save <file_path>`: Save the last successful script to a file.
  - `/stats`: Show execution statistics for enhanced mode.
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
            
        spinner = Spinner("dots", text=" Agent is thinking...")
        truncated_query = escape(user_input[:70] + '...' if len(user_input) > 70 else user_input)
        context_title = f"Agent 🤖  [dim]: {truncated_query}[/dim]"
        assistant_panel = Panel(spinner, title=context_title, border_style="yellow", title_align="left")
        
        # 使用我们自定义的 StreamingStatic 类来创建 widget
        streaming_widget = StreamingStatic(assistant_panel, id=streaming_widget_id)

        # 挂载临时 widget
        self.call_from_thread(output_container.mount, streaming_widget)

        self.post_message(StartSpinner(streaming_widget_id))
        
        final_renderable = None

        try:
            response_generator = self.agent.run_task(user_input, stream=True)
            full_response = ""
            first_token_received = False
            
            for part in response_generator:
                if isinstance(part, str):
                    if not first_token_received:
                        self.post_message(StopSpinner())
                        assistant_panel.border_style = "green"
                        first_token_received = True
                    
                    full_response += part
                    assistant_panel.renderable = Markdown(full_response, code_theme="monokai", inline_code_theme="monokai")
                    
                    def update_ui():
                        try:
                            widget_to_update = self.query_one(f"#{streaming_widget_id}", Static)
                            # 只需更新内容，滚动将由 on_resize 事件自动处理
                            widget_to_update.update(assistant_panel)
                        except Exception:
                            pass
                    
                    self.call_from_thread(update_ui)

                elif isinstance(part, LLMResponse) and not part.success:
                    self.post_message(StopSpinner())
                    error_message = f"[bold red]Error:[/bold red]\n{escape(part.error_message)}"
                    final_renderable = Panel(error_message, title="Agent", border_style="red", title_align="left")
                    break
            
            if final_renderable is None:
                response_markdown = Markdown(full_response, code_theme="monokai", inline_code_theme="monokai") if full_response else Text("Empty response.")
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
                update_type = update.get("type")
                message = escape(update.get("message", ""))

                if update_type == "planner_info":
                    subtype = update.get("subtype", "unknown")
                    content = update.get("content", "")
                    message = escape(update.get("message", ""))
                    
                    panel_title = f"[bold blue]Planner Info: {subtype.replace('_', ' ').title()}[/bold blue]"
                    renderable_content = None

                    if subtype in ["rag_context", "analysis_result"]:
                        renderable_content = Text(f"{message}\n\n[dim]{escape(str(content))}[/dim]")
                    elif subtype == "llm_prompt":
                        renderable_content = Text(f"{message}\n\n[dim]{escape(str(content))}[/dim]")
                    elif subtype == "llm_raw_response":
                        # 对 JSON 使用语法高亮
                        renderable_content = Syntax(str(content), "json", theme="monokai", word_wrap=True)
                    
                    if renderable_content:
                        self._write_to_log(Panel(renderable_content, title=panel_title, border_style="blue"))
                    else:
                        self._write_to_log(Panel(message, title=panel_title, border_style="blue"))

                elif update_type == "status":
                    self._write_to_log(Panel(f"⚙️ {message}", border_style="yellow"))
                
                elif update_type == "plan":
                    plan_text = ""
                    plan_data = update.get("plan", [])
                    complexity = update.get("complexity", "unknown")
                    
                    plan_text += f"[bold]Task Complexity:[/bold] {complexity.upper()}\n\n"
                    
                    if isinstance(plan_data, list):
                        for step in plan_data:
                            step_id = step.get("step_id", "?")
                            action = escape(str(step.get("action", "N/A")))
                            thought = escape(str(step.get("thought", "No thought.")))
                            args = step.get("args", {})
                            
                            plan_text += f"[b]{step_id}. {action}[/b]\n"
                            plan_text += f"   [dim]💭 {thought}[/dim]\n"
                            if args:
                                plan_text += f"   [dim]📋 Args: {escape(str(args))}[/dim]\n"
                            plan_text += "\n"
                    
                    self._write_to_log(Panel(plan_text, title="[yellow]📋 Execution Plan[/yellow]", border_style="yellow"))
                
                elif update_type == "step_start":
                    step_num = update.get('step', '?')
                    action = escape(str(update.get("action", "N/A")))
                    thought = escape(str(update.get("thought", "")))
                    log_entry = f"[bold green]▶️ Step {step_num}: {action}[/bold green]\n[dim]   💭 {thought}[/dim]"
                    self._write_to_log(Panel(log_entry, title=f"Step {step_num} Start", border_style="green"))

                elif update_type == "step_result":
                    step_num = update.get('step', '?')
                    success = update.get('success', False)
                    observation = update.get('observation', '')
                    execution_time = update.get('execution_time', 0)
                    
                    status_icon = "✅" if success else "❌"
                    status_color = "green" if success else "red"
                    
                    obs_text = f"{status_icon} [bold]Result:[/bold]\n{escape(observation)}"
                    if execution_time:
                        obs_text += f"\n\n[dim]⏱️ Execution time: {execution_time:.2f}s[/dim]"
                    
                    self._write_to_log(Panel(obs_text, title=f"[{status_color}]Step {step_num} Result[/{status_color}]", border_style=status_color))

                elif update_type == "recovery_plan":
                    original_step = update.get('original_step', '?')
                    new_steps = update.get('new_steps', [])
                    
                    recovery_text = f"[bold yellow]🔧 Recovery for Step {original_step}[/bold yellow]\n\n"
                    for step in new_steps:
                        step_id = step.get("step_id", "?")
                        action = escape(str(step.get("action", "N/A")))
                        thought = escape(str(step.get("thought", "")))
                        recovery_text += f"[b]{step_id}. {action}[/b]\n   [dim]💭 {thought}[/dim]\n"
                    
                    self._write_to_log(Panel(recovery_text, title="[yellow]🔄 Recovery Plan[/yellow]", border_style="yellow"))

                elif update_type == "final_result":
                    final_exec_result = update.get('result_object')
                    execution_time = update.get('execution_time', 0)
                    stats = update.get('stats', {})
                    
                    success_text = f"[bold green]✅ Enhanced Task Completed Successfully![/bold green]\n\n"
                    success_text += f"[dim]⏱️ Total execution time: {execution_time:.2f}s[/dim]\n"
                    success_text += f"[dim]📊 Steps executed: {stats.get('total_steps', 0)}[/dim]"
                    
                    self._write_to_log(Panel(success_text, title="[bold green]🎉 Success[/bold green]", border_style="green"))
                    
                    if final_exec_result and final_exec_result.executed_script:
                        self._write_to_log(Panel(
                            Syntax(final_exec_result.executed_script, "dos", theme="monokai", line_numbers=True),
                            title="[yellow]📜 Final Successful Script[/yellow]", border_style="yellow"
                        ))
                    
                    if final_exec_result and final_exec_result.data is not None:
                        result_str = str(final_exec_result.data)
                        self._write_to_log(Panel(result_str, title="[cyan]📊 Result Data[/cyan]", border_style="cyan"))
                
                elif update_type == "final_script":
                    script_content = update.get("script", "# No script found.")
                    self._write_to_log(Panel(
                        Syntax(script_content, "dos", theme="monokai", line_numbers=True, word_wrap=True),
                        title="[yellow]📜 Final Successful Script[/yellow]",
                        border_style="yellow"
                    ))

                elif update_type == "error":
                    error_msg = update.get('message', 'Unknown error')
                    stats = update.get('stats', {})
                    
                    error_text = f"[bold red]❌ Enhanced Task Failed[/bold red]\n\n"
                    error_text += f"[bold]Error:[/bold] {escape(error_msg)}\n\n"
                    error_text += f"[dim]📊 Steps attempted: {stats.get('total_steps', 0)}[/dim]\n"
                    error_text += f"[dim]🔄 Recovery attempts: {stats.get('recovery_attempts', 0)}[/dim]"
                    
                    self._write_to_log(Panel(error_text, title="[bold red]💥 Failure[/bold red]", border_style="red"))
                    
        except Exception as e:
            self._write_to_log(Panel(f"[bold red]An unexpected error occurred during the enhanced coding task:[/bold red]\n{e}", border_style="red"))
        
if __name__ == "__main__":
    try:
        project_path = os.path.dirname(os.path.abspath(__file__))
        log_dir = ".ddb_agent/logs"
        os.makedirs(log_dir, exist_ok=True)
        #setup_llm_logger(log_file_path=os.path.join(log_dir, "llm_requests.log"))

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