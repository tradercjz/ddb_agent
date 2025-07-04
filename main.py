
# project_path = "./dolphindbmodules"
# # 3. Build the index (only needs to be done once, or when files change)
# # index_manager = DDBIndexManager(project_path=project_path, index_file="/home/jzchen/ddb_agent/.ddb_agent/index.json")
# # index_manager.build_index(file_extensions=".dos", max_workers = 8)

# # exit(0) 

# rag_agent = DDBRAG(project_path=project_path, index_file="/home/jzchen/ddb_agent/.ddb_agent/index.json")

# # Example query
# user_query = "有什么量价因子"
# final_answer = rag_agent.chat(user_query)

# print("\n--- Final Answer ---")
# print(final_answer)


# file: ddb_agent/main.py

import os
from typing import Any, Dict, Generator, Tuple, Union
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.markdown import Markdown
from rich.live import Live
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

# 假设我们所有的核心逻辑都在 ddb_agent 包中
from agent import DDBAgent # 这是我们将所有逻辑组合起来的主Agent类
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

    - Type your query directly to chat with the agent.
    - Use the following slash commands for special actions:
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
    project_path = "/home/jzchen/ddb_agent" # 当前目录
    
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
        console.print(f"[bold red]Failed to initialize the agent:[/bold red] {e}")
        import traceback
        traceback.print_exc()