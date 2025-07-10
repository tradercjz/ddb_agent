
# file: ddb_agent/main.py

import os
from typing import Any, Dict, Generator, Tuple, Union
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.markdown import Markdown
from rich.live import Live
from rich.pretty import pprint 
from rich.spinner import Spinner
from rich.layout import Layout
from rich.align import Align
from rich.text import Text
from rich.markup import escape
from rich.syntax import Syntax

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

from utils.logger import setup_llm_logger

# 假设我们所有的核心逻辑都在 ddb_agent 包中
from agent.agent import DDBAgent # 这是我们将所有逻辑组合起来的主Agent类
from llm.llm_client import LLMResponse
from llm.llm_prompt import llm # 假设llm实例在这里初始化
from llm.models import ModelManager # 加载模型配置

# --- UI 和样式定义 ---

# 使用 Rich 创建一个控制台实例
console = Console()

# 为 prompt_toolkit 定义样式
prompt_style = Style.from_dict({
    'prompt': 'bg:#444444 #ffffff bold',
    'input': '#ffffff',
})

# 创建一个带历史记录的 PromptSession
session = PromptSession(
    history=FileHistory(os.path.expanduser('~/.ddb_agent_history')),
    auto_suggest=AutoSuggestFromHistory(),
)


def print_help_message():
    """Prints the help message for the user."""
    help_text = """
    **DDB-Coding-Agent Help**

    - Type your query directly to chat with the agent (RAG-based Q&A).
    - Use the following slash commands for special actions:
      - `/code <your task>`: Ask the agent to write and execute DolphinDB code.
      - `/save <file_path>`: Save the last successful script to a file.
      - `/new` or `/reset`: Start a new conversation session.
      - `/help`: Show this help message.
      - `/exit` or `/quit`: Exit the agent.
    """
    console.print(Panel(
        Markdown(help_text),
        title="[bold cyan]Help[/bold cyan]",
        border_style="blue"
    ))

def stream_out(
    response_generator: Generator[Union[str, LLMResponse], None, None],
    title: str = "Agent",
    final_title: str = "Agent Response"
) -> Tuple[str, Any]:
    """
    Handles streaming output to the console with a loading status,
    then seamlessly transitions to a live-updated panel.
    """
    assistant_response = ""
    last_meta = None
    live: Live = None

    with Status("[bold yellow]Agent is thinking...[/bold yellow]", console=console, spinner="dots") as status:
        first_token_received = False
        
        for part in response_generator:
            if isinstance(part, str):
                if not first_token_received:
                    # 收到第一个token，停止status，启动live
                    status.stop()
                    live = Live(console=console, auto_refresh=False, vertical_overflow="visible")
                    live.start()
                    first_token_received = True
                
                assistant_response += part
                if live:
                    md = Markdown(assistant_response, code_theme="monokai")
                    live.update(Panel(
                        md,
                        title=f"[bold green]{title}[/bold green]",
                        border_style="green"
                    ), refresh=True)

            elif isinstance(part, LLMResponse):
                # 收到最后的元数据
                last_meta = part
                if not part.success:
                    # 如果有错误，也在这里处理
                    if live:
                        live.update(Panel(
                            f"[bold red]Error:[/bold red]\n{part.error_message}",
                            title="[bold red]Error[/bold red]",
                            border_style="red"
                        ), refresh=True)
                    else: # 如果在第一个token前就出错
                        status.stop()
                        console.print(Panel(
                            f"[bold red]Error:[/bold red]\n{part.error_message}",
                            title="[bold red]Error[/bold red]",
                            border_style="red"
                        ))
                break # 收到元数据或错误后，流结束

    if live:
        live.stop()
    
    return assistant_response, last_meta


# --- 主循环 ---
def main_loop(agent: DDBAgent):
    """The main Read-Eval-Print Loop (REPL) for the agent."""

    # 1. 设置 LLM 请求日志文件
    # 日志会保存在 .ddb_agent/logs/llm_requests.log
    log_dir = ".ddb_agent/logs"
    os.makedirs(log_dir, exist_ok=True)
    setup_llm_logger(log_file_path=os.path.join(log_dir, "llm_requests.log"))
    
    console.print(Panel(
        "[bold green]Welcome to the DDB-Coding-Agent!_Type `/help` for commands.[/bold green]",
        title="[bold magenta]DDB Agent[/bold magenta]"
    ))

    while True:
        try:
            # 使用 prompt_toolkit 获取用户输入
            user_input = session.prompt(
                [('class:prompt', ' You > ')],
                style=prompt_style
            ).strip()

            if not user_input:
                continue

            # --- 命令处理 ---
            if user_input.lower() in ['/exit', '/quit']:
                console.print("[bold yellow]Exiting agent. Goodbye![/bold yellow]")
                break
            
            if user_input.lower() in ['/new', '/reset']:
                agent.start_new_session()
                console.print(Panel("[bold green]New session started.[/bold green]", border_style="green"))
                continue
            
            if user_input.lower() == '/help':
                print_help_message()
                continue
            
            if user_input.lower().startswith('/save '):
                file_path = user_input[6:].strip()
                if not file_path:
                    console.print(Panel("[bold yellow]Please provide a file path after /save.[/bold yellow]", border_style="yellow"))
                    continue
                
                # Call the agent's save method
                success, message = agent.save_last_script(file_path)

                if success:
                    console.print(Panel(f"[bold green]✅ Success![/bold green]\n{message}", border_style="green"))
                else:
                    console.print(Panel(f"[bold red]❌ Failed![/bold red]\n{message}", border_style="red"))
                
                continue # Move to the next loop iteration

            # --- 新增: /code 命令处理 ---
            if user_input.lower().startswith('/code '):
                task_description = user_input[6:].strip()
                if not task_description:
                    console.print(Panel("[bold yellow]Please provide a task description after /code.[/bold yellow]", border_style="yellow"))
                    continue

                console.print(Panel(f"[bold blue]Received coding task:[/bold blue] {task_description}", title="[bold magenta]Coding Task[/bold magenta]"))

                # 调用改造后的生成器方法
                response_generator = agent.run_coding_task_with_planner(task_description)

                # --- 使用 rich.Live 来创建实时更新的界面 ---
                # 初始化界面元素
                status_spinner = Spinner("dots", "Agent is thinking...")
                current_plan_panel = Panel("No plan generated yet.", title="[yellow]Current Plan[/yellow]", border_style="yellow")
                execution_log = [] # 存储执行日志
                
                final_task_outcome = None

                # 创建一个布局
                layout = Layout()
                layout.split_column(
                    Layout(name="header", size=3),
                    Layout(name="body")
                )
                layout["header"].update(Align.center(status_spinner))
                layout["body"].split_row(
                    Layout(current_plan_panel, name="plan"),
                    Layout(Panel("", title="[cyan]Execution Log[/cyan]", border_style="cyan"), name="log")
                )

                with Live(layout, console=console, screen=True, auto_refresh=False) as live:
                    for update in response_generator:
                        update_type = update.get("type")

                        if update_type == "status":
                            # 状态消息通常是开发者自己写的，比较安全，但转义一下更保险
                            status_spinner.text = escape(update["message"])
                            live.update(layout, refresh=True)
                        
                        elif update_type == "plan":
                            # 更新计划面板
                            plan_text = ""
                            # --- 这是修复的关键 ---
                            # 确保从 update 中获取的 plan 是一个列表，如果不存在则为空列表
                            plan_data = update.get("plan", [])
                            if isinstance(plan_data, list):
                                for i, step in enumerate(plan_data):
                                    # 对所有来自LLM的动态字符串进行 .get() 安全访问和 escape 转义
                                    action = escape(str(step.get("action", "N/A")))
                                    thought = escape(str(step.get("thought", "No thought provided.")))
                                    plan_text += f"[b]{i+1}. {action}[/b]\n   [dim]Thought: {thought}[/dim]\n"
                            
                            current_plan_panel.renderable = plan_text
                            live.update(layout, refresh=True)

                        elif update_type == "step_start":
                            # 你的代码已经在这里报错，说明 plan 的内容有问题
                            # 我们同样要确保这里的转义是健壮的
                            step_num = update.get('step', '?')
                            action = escape(str(update.get("action", "N/A")))
                            thought = escape(str(update.get("thought", "")))
                            
                            log_entry = f"[bold green]▶️ Step {step_num}: {action}[/bold green]\n[dim]   Thought: {thought}[/dim]"
                            execution_log.append(log_entry)
                            
                            # 更新日志面板
                            # 使用 "\n---\n".join(...) 的方式是正确的
                            layout["log"].update(Panel("\n---\n".join(execution_log), title="[cyan]Execution Log[/cyan]", border_style="cyan"))
                            live.update(layout, refresh=True) # 错误发生在这里
                        elif update_type == "step_result":
                            # 对工具返回的 observation 进行转义，这是最关键的一步！
                            escaped_observation = escape(update['observation'])
                            log_entry = f"   [bold]Observation:[/bold]\n   {escaped_observation}"
                            execution_log.append(log_entry)
                            layout["log"].update(Panel("\n---\n".join(execution_log), title="[cyan]Execution Log[/cyan]", border_style="cyan"))
                            live.update(layout, refresh=True)
                        if update_type == "final_result" or update_type == "error":
                            final_task_outcome = update
                            if update_type == "error":
                                break # 如果是错误，提前终止直播

                console.print() # 打印一个空行，为了格式美观
                if final_task_outcome:
                    if final_task_outcome["type"] == "final_result":
                        final_exec_result = final_task_outcome.get('result_object')
                        # Start printing the success panel
                        console.print(Panel(
                            "[bold green]✅ Task Completed Successfully![/bold green]",
                            title="[bold green]Success[/bold green]",
                            border_style="green"
                        ))

                        # --- DISPLAY THE FINAL SCRIPT ---
                        if final_exec_result and final_exec_result.executed_script:
                            console.print(Panel(
                                Syntax(final_exec_result.executed_script, "dos", theme="monokai", line_numbers=True),
                                title="[yellow]Final Successful Script[/yellow]",
                                border_style="yellow"
                            ))
                        
                        console.print(Panel(
                            "[bold green]✅ Task Completed Successfully![/bold green]",
                            title="[bold green]Success[/bold green]",
                            border_style="green"
                        ))
                        console.print("[bold cyan]Result Data:[/bold cyan]")
                        # 使用 rich.pretty.pprint 美观地打印结果
                        pprint(final_task_outcome.get('result', 'No data returned.'), expand_all=True)
                    
                    elif final_task_outcome["type"] == "error":
                        console.print(Panel(
                            f"[bold red]❌ Task Failed.[/bold red]\n\n[bold]Final Error:[/bold]\n{escape(final_task_outcome.get('message', 'Unknown error.'))}",
                            title="[bold red]Failure[/bold red]",
                            border_style="red"
                        ))
                else:
                    # 如果循环因为某些原因（如KeyboardInterrupt）提前退出，没有最终结果
                    console.print(Panel("[bold yellow]Task execution was interrupted or finished without a definitive result.[/bold yellow]", border_style="yellow"))

                console.print("\n[bold green]Coding task finished. Press Enter to continue...[/bold green]")
                input() # 等待用户按键，以便查看最终结果
                continue

            full_response_content = ""
            error_message = None
            live: Live = None
            
            # 1. 启动 Status 加载动画
            status = Status("[bold yellow]Agent is thinking...[/bold yellow]", console=console, spinner="dots")
            status.start()

            try:
                # 调用 agent.run_task 获取生成器
                # 假设 agent.run_task 现在返回一个流
                response_generator = agent.run_task(user_input, stream=True)
                first_token_received = False

                for part in response_generator:
                    if not first_token_received:
                        # 收到第一个 token，停止 status，启动 live
                        status.stop()
                        live = Live(console=console, auto_refresh=False, transient=True)
                        live.start()
                        first_token_received = True
                    
                    if isinstance(part, str):
                        full_response_content += part
                        if live:
                            # 为了避免滚动重复，只显示最后一部分内容
                            terminal_height = console.height
                            lines = full_response_content.splitlines()
                            display_lines = lines[-(terminal_height - 5):]
                            display_content = "\n".join(display_lines)
                            if len(lines) > len(display_lines):
                                display_content = f"[dim]... (scrolling) ...[/dim]\n{display_content}"
                            
                            md = Markdown(display_content, code_theme="monokai")
                            live.update(Panel(
                                md,
                                title="[bold green]Agent[/bold green]",
                                border_style="green",
                                title_align="left"
                            ), refresh=True)
                    elif isinstance(part, LLMResponse):
                        if not part.success:
                            error_message = part.error_message
                        break # 流结束
            finally:
                # 确保 Status 和 Live 都被正确停止
                if status:
                    status.stop()
                if live and live.is_started:
                    live.stop()

            # --- Live 结束后，打印最终的完整结果 ---
            if error_message:
                console.print(Panel(
                    f"[bold red]Error:[/bold red]\n{error_message}",
                    title="[bold red]Error[/bold red]",
                    border_style="red"
                ))
            elif full_response_content:
                console.print(Panel(
                    Markdown(full_response_content, code_theme="monokai"),
                    title="[bold green]Agent[/bold green]",
                    border_style="green",
                    title_align="left"
                ))

        except KeyboardInterrupt:
            # 允许用户通过 Ctrl+C 安全退出
            console.print("\n[bold yellow]Interrupted by user. Exiting...[/bold yellow]")
            break
        except Exception as e:
            import traceback
            traceback.print_exc()
            # 捕获意外错误，并打印，防止程序崩溃
            console.print(Panel(
                f"[bold red]An unexpected error occurred:[/bold red]\n{e}",
                title="[bold red]Error[/bold red]",
                border_style="red"
            ))
            


if __name__ == "__main__":
    # --- 初始化 ---
    
    # 1. 设置项目路径
    # 在实际应用中，这可能来自命令行参数
    project_path = current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. 加载模型配置
    # ModelManager 会自动从 models.json 加载
    ModelManager.load_models()

    # 3. 初始化主 Agent
    # 假设 'deepseek-chat' 是在 models.json 中定义的别名
    # 并且对应的模型有 64k 的窗口
    try:
        ddb_agent = DDBAgent(
            project_path=project_path,
            model_name="deepseek-chat", # 或者从配置中读取默认模型
            max_window_size=64000
        )
        
        # 4. 启动主循环
        main_loop(ddb_agent)

    except Exception as e:
        error_text = Text(str(e))
        # 先打印静态部分，再打印 Text 对象
        console.print("[bold red]Failed to initialize the agent:[/bold red]", error_text)
        import traceback
        traceback.print_exc()