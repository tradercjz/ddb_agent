# FILE: test_mcp_integration.py

import asyncio
import os
import shutil
from rich.pretty import pprint
from rich.panel import Panel
from rich.console import Console

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

async def main():
    """
    主测试函数，按顺序执行 MCP 的安装、启动、使用和停止流程。
    """
    console.rule("[bold cyan]MCP 集成测试开始[/bold cyan]", style="cyan")

    # 为了保证测试环境的纯净，我们先清理旧的 MCP 缓存和服务器
    if os.path.exists(".mcp_cache"):
        shutil.rmtree(".mcp_cache")
        console.print("[yellow]已清理旧的 .mcp_cache 目录。[/yellow]")
    if os.path.exists(".mcp_servers"):
        shutil.rmtree(".mcp_servers")
        console.print("[yellow]已清理旧的 .mcp_servers 目录。[/yellow]")


    # --- 1. 初始化核心组件 ---
    console.rule("[bold]步骤 1: 初始化组件[/bold]")
    try:
        # 加载模型配置
        ModelManager.load_models()

        # 初始化 Agent (Agent 内部会创建 ToolManager)
        agent = DDBAgent(
            project_path=os.getcwd(),
            model_name="deepseek-chat", # 使用一个快速的模型
            max_window_size=64000
        )
        
        # 为了测试，我们直接创建和使用 MCP 管理器
        market_manager = MCPMarketManager()
        server_manager = MCPServerManager(market_manager)
        
        # 将我们手动创建的 server_manager 关联到 agent 的 tool_manager (模拟TUI应用的行为)
        # 这是为了让 agent 的 `enhanced_executor` 能够与我们控制的 `server_manager` 通信
        # 注意：在实际应用中，这种关联发生在顶层应用（如 DDBAgentApp）中
        # 这里我们为了测试而直接操作
        if agent.enhanced_executor.tool_manager.enable_mcp:
            agent.enhanced_executor.tool_manager.mcp_server_manager = server_manager
            agent.enhanced_executor.tool_manager.mcp_tool_adapter.server_manager = server_manager


        console.print("[green]✅ Agent 和 MCP 管理器初始化成功。[/green]")
    except Exception as e:
        console.print_exception()
        return

    # --- 2. 安装 Filesystem 服务器 ---
    server_to_test = "filesystem"
    console.rule(f"[bold]步骤 2: 安装 '{server_to_test}' 服务器[/bold]")
    
    console.print(f"正在尝试安装 '{server_to_test}' 服务器... (这可能需要一些时间)")
    install_success = await market_manager.install_server(server_to_test)
    
    assert install_success, f"服务器 '{server_to_test}' 安装失败!"
    console.print(f"[green]✅ 服务器 '{server_to_test}' 安装成功。[/green]")


    # --- 3. 启动 Filesystem 服务器 ---
    console.rule(f"[bold]步骤 3: 启动 '{server_to_test}' 服务器[/bold]")
    
    start_success = await server_manager.start_server(server_to_test, "./")
    assert start_success, f"服务器 '{server_to_test}' 启动失败!"

    console.print(f"等待服务器 '{server_to_test}' 完全初始化... (等待3秒)")
    await asyncio.sleep(3) # 给予服务器进程足够的时间来完成内部初始化和能力发现

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
    
    task_description = "请创建一个名为 'mcp_test_file.txt' 的文件，内容是 'Hello from MCP!'"
    console.print(Panel(f"[bold]任务描述:[/bold] {task_description}", title="Agent 任务", border_style="magenta"))

    try:
        response_generator = agent.run_enhanced_coding_task(task_description)
        
        final_result_update: Optional[TaskExecutionEnd] = None
        for update in response_generator:
            # 使用 isinstance 进行类型检查
            if isinstance(update, BaseExecutorStatus):
                # 打印通用消息
                console.print(Panel(f"[dim]Type: {update.subtype}[/dim]\n{update.message}", 
                                    title=f"Agent Update: {update.subtype}", 
                                    border_style="blue", 
                                    title_align="left"))
                
                # 如果是计划生成结束，可以打印计划详情
                if isinstance(update, PlanGenerationEnd):
                    console.print("[bold yellow]执行计划:[/bold yellow]")
                    pprint(update.plan)
                
                # 捕获最终的任务结束状态
                if isinstance(update, TaskExecutionEnd):
                    final_result_update = update

        console.print("\n[bold green]Agent 任务执行完成。[/bold green]")
        
        # --- 断言和验证 ---
        assert final_result_update is not None, "未能捕获到任务结束状态 (TaskExecutionEnd)!"
        
        pprint(final_result_update) # 打印最终的状态对象
        
        # 从最终状态对象中获取结果并进行断言
        assert final_result_update.success, "Agent 任务执行失败!"
        assert final_result_update.final_result is not None, "最终结果对象 (ExecutionResult) 为空!"
        assert final_result_update.final_result.success, "最终结果对象显示执行失败!"

        # 验证文件是否真的被创建
        console.print("\n[bold]验证文件创建结果...[/bold]")
        assert os.path.exists("mcp_test_file.txt"), "文件 'mcp_test_file.txt' 未被创建!"
        with open("mcp_test_file.txt", "r") as f:
            content = f.read()
            assert content == "Hello from MCP!", "文件内容不正确!"
        
        console.print("[green]✅ 验证成功：文件已正确创建。[/green]")
        os.remove("mcp_test_file.txt") # 清理测试文件

    except Exception as e:
        console.print_exception()

    # --- 6. 停止服务器 ---
    console.rule(f"[bold]步骤 6: 停止 '{server_to_test}' 服务器[/bold]")
    
    stop_success = await server_manager.stop_server(server_to_test)
    assert stop_success, f"服务器 '{server_to_test}' 停止失败!"
    
    is_running_after_stop = server_manager.is_server_running(server_to_test)
    assert not is_running_after_stop, "服务器停止后状态仍为运行中!"
    console.print(f"[green]✅ 服务器 '{server_to_test}' 成功停止。[/green]")


    console.rule("[bold green]MCP 集成测试全部通过！[/bold green]", style="green")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n测试被用户中断。")