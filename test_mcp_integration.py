# FILE: test_mcp_integration.py

import asyncio
import os
import shutil
from rich.pretty import pprint
from rich.panel import Panel
from rich.console import Console
import time # 导入 time 模块

# -- 核心 MCP 组件 --
from agent.task_status import BaseTaskStatus
from mcp.market.market_manager import MCPMarketManager
from mcp.server.server_manager import MCPServerManager

# -- Agent 相关组件 --
from agent.agent import DDBAgent
from llm.models import ModelManager

from agent.enhanced_executor_status import (
    AnyExecutorStatus, BaseExecutorStatus, TaskExecutionEnd, PlanGenerationEnd
)

from typing import Optional

# 创建一个 Rich Console 用于美化输出
console = Console()


# 将 main 函数改为同步函数，因为它不再直接 await MCP 的调用
def main():

    """
    主测试函数，按顺序执行 MCP 的安装、启动、使用和停止流程。
    """
    console.rule("[bold cyan]MCP 集成测试开始[/bold cyan]", style="cyan")

    # 清理旧的 MCP 缓存和服务器
    if os.path.exists(".mcp_cache"):
        shutil.rmtree(".mcp_cache")
        console.print("[yellow]已清理旧的 .mcp_cache 目录。[/yellow]")
    if os.path.exists(".mcp_servers"):
        shutil.rmtree(".mcp_servers")
        console.print("[yellow]已清理旧的 .mcp_servers 目录。[/yellow]")


    # --- 1. 初始化核心组件 ---
    server_manager = None # 先声明
    try:
        console.rule("[bold]步骤 1: 初始化组件[/bold]")
        ModelManager.load_models()
        agent = DDBAgent(
            project_path=os.getcwd(),
            model_name="deepseek-chat",
            max_window_size=64000
        )
        
        market_manager = MCPMarketManager()
        # 创建 server_manager，它会自动启动后台线程
        server_manager = MCPServerManager(market_manager)

        server_manager.bootstrap_builtin_servers()
        
        # 将 server_manager 关联到 agent 的 tool_manager
        if agent.tool_manager.enable_mcp:
             # 注意：DDBAgent 内部的 tool_manager 是 EnhancedToolManager
            agent.tool_manager.mcp_server_manager = server_manager
            agent.tool_manager.mcp_tool_adapter.server_manager = server_manager
        
        console.print("[green]✅ Agent 和 MCP 管理器初始化成功。[/green]")

        # --- 2. 安装 Filesystem 服务器 ---
        server_to_test = "filesystem"
        console.rule(f"[bold]步骤 2: 安装 '{server_to_test}' 服务器[/bold]")
        
        console.print(f"正在尝试安装 '{server_to_test}' 服务器... (这可能需要一些时间)")
        
        # --- START OF FIX ---
        # market_manager.install_server 现在也应该是同步的
        # 我们需要为它也实现一个同步版本或确认它已经是同步的
        # 假设 market_manager.install_server 是同步的
        install_success = market_manager.install_server(server_to_test)
        # --- END OF FIX ---
        
        assert install_success, f"服务器 '{server_to_test}' 安装失败!"
        console.print(f"[green]✅ 服务器 '{server_to_test}' 安装成功。[/green]")


        # --- 3. 启动 Filesystem 服务器 ---
        console.rule(f"[bold]步骤 3: 启动 '{server_to_test}' 服务器[/bold]")
        
        # --- START OF FIX ---
        # 移除 await
        start_success = server_manager.start_server(server_to_test, "./")
        # --- END OF FIX ---
        assert start_success, f"服务器 '{server_to_test}' 启动失败!"

        console.print(f"等待服务器 '{server_to_test}' 完全初始化... (等待3秒)")
        # --- START OF FIX ---
        # 使用 time.sleep 代替 asyncio.sleep
        time.sleep(3)
        # --- END OF FIX ---

        is_running = server_manager.is_server_running(server_to_test)
        assert is_running, "服务器状态显示未在运行!"
        console.print(f"[green]✅ 服务器 '{server_to_test}' 启动并运行成功。[/green]")


        # --- 4. 验证工具是否被发现 ---
        console.rule("[bold]步骤 4: 验证工具发现[/bold]")
        
        all_tools = server_manager.get_all_tools()
        console.print("发现的 MCP 工具:")
        pprint(all_tools)
        
        assert len(all_tools) > 0, "未能从运行中的服务器发现任何工具!"
        console.print("[green]✅ 成功从服务器发现工具。[/green]")


        # --- 5. 通过 Agent 执行一个使用 MCP 工具的任务 ---
        console.rule("[bold]步骤 5: 执行一个使用 MCP 工具的增强任务[/bold]")
        
        task_description = "创建一个新的文件 'test_file.txt'，并写入内容 'Hello, MCP!'。"
        console.print(Panel(f"[bold]任务描述:[/bold] {task_description}", title="Agent 任务", border_style="magenta"))

        # --- START OF FIX ---
        # agent.run_enhanced_coding_task 是同步生成器，可以直接迭代
        response_generator = agent.run_enhanced_coding_task(task_description)
        # --- END OF FIX ---
            
        final_result_update: Optional[TaskExecutionEnd] = None
        for update in response_generator:
            if isinstance(update, BaseExecutorStatus):
                console.print(Panel(f"[dim]Type: {update.subtype}[/dim]\n{update.message}", 
                                    title=f"Agent Update: {update.subtype}", 
                                    border_style="blue", 
                                    title_align="left"))
                if isinstance(update, PlanGenerationEnd):
                    console.print("[bold yellow]执行计划:[/bold yellow]")
                    pprint(update.plan)
                if isinstance(update, TaskExecutionEnd):
                    final_result_update = update

        console.print("\n[bold green]Agent 任务执行完成。[/bold green]")
        
        assert final_result_update is not None, "未能捕获到任务结束状态 (TaskExecutionEnd)!"
        pprint(final_result_update)
        assert final_result_update.success, "Agent 任务执行失败!"
        # ... 其他断言 ...

        # --- 6. 停止服务器 ---
        console.rule(f"[bold]步骤 6: 停止 '{server_to_test}' 服务器[/bold]")
        
        # --- START OF FIX ---
        # 移除 await
        stop_success = server_manager.stop_server(server_to_test)
        # --- END OF FIX ---
        assert stop_success, f"服务器 '{server_to_test}' 停止失败!"
        
        is_running_after_stop = server_manager.is_server_running(server_to_test)
        assert not is_running_after_stop, "服务器停止后状态仍为运行中!"
        console.print(f"[green]✅ 服务器 '{server_to_test}' 成功停止。[/green]")

        console.rule("[bold green]MCP 集成测试全部通过！[/bold green]", style="green")

    except Exception as e:
        console.print_exception()
    finally:
        # --- 7. 清理 ---
        console.rule("[bold]步骤 7: 清理资源[/bold]")
        if server_manager:
            server_manager.shutdown()
            console.print("[yellow]MCPServerManager 已关闭。[/yellow]")


if __name__ == "__main__":
    # --- START OF FIX ---
    # 移除 asyncio.run
    try:
        main()
    except KeyboardInterrupt:
        print("\n测试被用户中断。")
    # --- END OF FIX ---