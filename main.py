
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
from typing import Dict
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

# 假设我们所有的核心逻辑都在 ddb_agent 包中
from agent import DDBAgent # 这是我们将所有逻辑组合起来的主Agent类
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

            # --- 调用 Agent 核心逻辑 ---
            with console.status("[bold yellow]Agent is thinking...[/bold yellow]", spinner="dots"):
                # 假设 run_task 是我们之前设计的，封装了所有逻辑的方法
                assistant_response = agent.run_task(user_input)

            # --- 格式化并打印输出 ---
            console.print(Panel(
                Markdown(assistant_response, code_theme="monokai"),
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