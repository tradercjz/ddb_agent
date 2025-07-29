# file: ddb_agent/agent.py (之前在main.py中虚构的，现在正式实现)

import datetime
import json
import os
from typing import Generator, List, Dict, Any, Tuple, Union
from agent.code_executor import CodeExecutor
from agent.coding_task_state import CodingTaskState
from agent.execution_result import ExecutionResult
from agent.prompts import debugging_planner, fix_script_from_error, generate_initial_script
from agent.task_status import AnyTaskStatus, PlanGenerationEnd, PlanGenerationStart, StepExecutionEnd, StepExecutionStart, TaskEnd, TaskError, TaskStart
from llm.llm_client import LLMResponse, StreamChunk
from rag.rag_status import AnyRagStatus
from session.session_manager import SessionManager
from context.context_builder import ContextBuilder
from rag.rag_entry import DDBRAG
from llm.llm_prompt import llm # 假设llm实例在这里
from snippets.snippet_manager import SnippetManager

from rich.pretty import pprint

from agent.tools.ddb_tools import  RunDolphinDBScriptTool
from agent.tools.enhanced_ddb_tools import (
    InspectDatabaseTool, ListTablesTool, DescribeTableTool, 
    ValidateScriptTool, QueryDataTool, CreateSampleDataTool, OptimizeQueryTool,
    GetFunctionDocumentationTool
)
from utils.json_parser import parse_json_string


from agent.enhanced_executor_status import AnyExecutorStatus, TaskExecutionEnd, FinalScriptExtracted
from agent.enhanced_planner import EnhancedPlanner
from agent.enhanced_executor import EnhancedExecutor
from agent.tool_manager_enhanced import EnhancedToolManager

class DDBAgent:
    """
    The main agent orchestrating all components: session, RAG, context, and LLM.
    """
    def __init__(self, project_path: str, model_name: str, max_window_size: int, index_file: str = None):
        self.project_path = project_path
        self.session_manager = SessionManager(project_path=project_path)
        self.snippet_manager = SnippetManager(project_path=project_path)
        self.context_builder = ContextBuilder(model_name=model_name, max_window_size=max_window_size)
        self.rag = DDBRAG(project_path=project_path, index_file=index_file)
        self.llm_model_name = model_name
        self.code_executor = CodeExecutor()
        # 初始化工具管理器（包含增强工具集）
        self.tool_manager = EnhancedToolManager([
            # 基础工具
            RunDolphinDBScriptTool(executor=self.code_executor),
            GetFunctionDocumentationTool("/home/jzchen/ddb_agent"),
            # 增强工具集
            InspectDatabaseTool(executor=self.code_executor),
            ListTablesTool(executor=self.code_executor),
            DescribeTableTool(executor=self.code_executor),
            QueryDataTool(executor=self.code_executor),
            CreateSampleDataTool(executor=self.code_executor),
            OptimizeQueryTool(executor=self.code_executor)
        ])
        
        # 初始化增强规划器和执行器
        self.enhanced_planner = EnhancedPlanner(self.tool_manager, self.rag)
        self.enhanced_executor = EnhancedExecutor(self.tool_manager, self.enhanced_planner)
        self.last_successful_script: str | None = None 

        # 定义一个通用的聊天Prompt
        @llm.prompt()
        def _default_chat_prompt(conversation_history: List[Dict[str, str]]):
            """
            You are a helpful DolphinDB assistant. Continue the conversation naturally.
            The user's latest message is the last one in the history.
            """
        
        self.chat_prompt_func = _default_chat_prompt

    def start_new_session(self):
        """Starts a new chat session."""
        self.session_manager.new_session()


    def run_task(self, user_input: str, task_type: str = 'chat') -> Generator[Union[AnyRagStatus, StreamChunk], None, LLMResponse]:
        """
        Handles a user request by orchestrating RAG, context building, and LLM interaction.
        """
        # 1. 更新会话历史
        self.session_manager.add_message('user', user_input)
        full_conversation_history = self.session_manager.get_history()

        # 2. 使用 RAG 检索相关文件上下文
        # 我们用最新的用户输入去检索
        relevant_files = yield from self.rag.retrieve(user_input, top_k=5)

        # 3. 准备构建上下文所需的所有材料
        system_prompt = "You are a world-class DolphinDB expert. Answer the user's query based on the provided context. If file context is provided, prioritize it. Be concise, accurate, and provide code examples where appropriate."
        
        # 4. 使用 ContextBuilder 构建最终的、经过剪枝的上下文
        # 注意：我们将完整的历史和检索到的文件都传给它
        final_messages = self.context_builder.build(
            system_prompt=system_prompt,
            conversations=full_conversation_history,
            file_sources=relevant_files,
            task_type=task_type,
            file_pruning_strategy='extract'
        )

        assistant_response = yield from self.chat_prompt_func(
            conversation_history=final_messages
        )

        self.session_manager.add_message('assistant', assistant_response.content)
        self.session_manager.save_session()

        return assistant_response
    
    def run_coding_task(self, user_input: str):
        """
        Orchestrates the iterative process of generating, executing, and fixing code.
        """  
        print(f"--- Starting new coding task for: '{user_input}' ---")

        # 1. 初始 RAG
        print("Step 1: Retrieving context with RAG...")
        initial_context = self.rag.retrieve(user_input, top_k=5)
        # 将 Document 列表转换为单个字符串
        context_str = "\n---\n".join(
            f"File: {doc.file_path}\n\n{doc.source_code}" for doc in initial_context
        )

        # 2. 初始化任务状态
        state = CodingTaskState(
            original_query=user_input,
            rag_context=context_str
        )

        # 3. 生成第一版脚本
        print("Step 2: Generating initial script...")
        state.current_code = generate_initial_script(
            user_query=state.original_query,
            rag_context=state.rag_context
        )
        print(f"Initial script generated:\n{state.current_code}")

        # 4. 进入核心的 "执行-修正" 循环
        while not state.has_reached_max_attempts:
            print(f"\n--- Attempt {state.refinement_attempts + 1}/{state.max_attempts} ---")
            
            # 执行代码
            print("Executing script...")
            exec_result = self.code_executor.run(state.current_code)
            state.add_execution_result(exec_result)

            # 分析结果
            if exec_result.success:
                print("✅ Task Succeeded!")
                print("source code:",state.current_code)  # 输出最终代码
                print("Final Result Data:")
                print(exec_result.data)
                # 任务成功，退出循环
                return exec_result
            
            # 如果失败，进行修正
            print(f"Script failed. Error: {exec_result.error_message}")
            print("Attempting to self-correct...")
            
            last_error = state.get_last_error()
            
            # (可选) 针对错误进行 RAG
            # error_context = self.rag.retrieve(last_error, top_k=2)
            # combined_context = state.rag_context + "\n---\n" + error_context_str
            
            # 调用修正 prompt
            state.current_code = fix_script_from_error(
                original_query=state.original_query,
                failed_code=state.current_code,
                error_message=last_error,
                rag_context=state.rag_context # 使用更新后的上下文
            )
            print(f"Generated new corrected script:\n{state.current_code}")
            
            state.refinement_attempts += 1
        
        # 如果循环结束仍未成功
        print("❌ Task Failed after maximum attempts.")
        return state.execution_history[-1] # 返回最后一次的失败结果
    
    def run_coding_task_with_planner(self, user_input: str) -> Generator[Union[AnyTaskStatus, StreamChunk], None, ExecutionResult]:
        """
        Orchestrates the plan-and-execute loop for a coding task, yielding state updates.
        """
        yield TaskStart(
            task_description=user_input,
            message="🚀 Starting new PLAN-and-EXECUTE coding task..."
        )

        # 2. 生成初始计划
        yield PlanGenerationStart(
            message="🧠 Generating initial plan...",
            reason="initial"
        )

        # 这里我们简化，直接生成一个包含run_dolphindb_script的计划
        # 实际中可能需要一个Planner来生成
        try:
            initial_script_gen = generate_initial_script(user_query=user_input, rag_context="...") # 假设有rag_context
            try:
                while True:
                    yield next(initial_script_gen)
            except StopIteration as e:
                initial_script = e.value

            plan = [
                {
                    "step": 1, 
                    "thought": "I will start by generating a script to address the user's request and then execute it.", 
                    "action": "run_dolphindb_script", 
                    "args": {"script": initial_script.content}
                }
            ]
            yield PlanGenerationEnd(plan=plan, message="✅ Initial plan generated.")
        except Exception as e:
            yield TaskError(message=f"Failed to generate initial script: {e}", error_details=str(e))
            return ExecutionResult(success=False, error_message=str(e))

        # 3. 执行计划循环
        step_index = 0
        execution_context = {}

        total_failed_steps = 0

        final_script = ""
        while step_index < len(plan):
            current_step = plan[step_index]
            action = current_step["action"]
            args = current_step["args"]
            thought = current_step["thought"]

            yield StepExecutionStart(
                step_index=step_index + 1,
                total_steps=len(plan),
                step_info=current_step,
                message=f"▶️ Executing step {step_index + 1}/{len(plan)}: {current_step.get('action')}"
            )

            # 执行工具调用
            tool_result = self.tool_manager.call_tool(action, args)

            is_success = True
            if isinstance(tool_result, ExecutionResult):
                observation_str = str(tool_result.data) if tool_result.success else f"Execution failed. Error:\n{tool_result.error_message}"
                is_success = tool_result.success
            else: # It's a string from another tool like get_function_signature
                observation_str = str(tool_result)

            yield StepExecutionEnd(
                step_index=step_index + 1,
                observation=observation_str,
                is_success=is_success,
                message=f"{'✅' if is_success else '❌'} Step {step_index + 1} finished.",
                script=args.get("script", None) if action == "run_dolphindb_script" else None
            )

            final_script += args.get("script", None) if action == "run_dolphindb_script" else None

            
            # 检查是否需要启动调试子流程
            if action == "run_dolphindb_script" and  not is_success:
                total_failed_steps += 1
                if total_failed_steps >= 5:
                    yield TaskError(
                        message="连续执行失败超过3次，任务失败退出...",
                        error_details=observation_str
                    )

                yield PlanGenerationStart(
                    message="🛠️ Execution failed. Entering debugging sub-task to generate a new plan...",
                    reason="debug_fix"
                )
                
                failed_code = args["script"]
                error_message = observation_str.split("Error:\n", 1)[1]
                tool_defs_str = json.dumps(self.tool_manager.get_tool_definitions(), indent=2)

                try:
                    new_plan_str_gen = debugging_planner(
                        original_query=user_input,
                        failed_code=failed_code,
                        error_message=error_message,
                        tool_definitions=tool_defs_str
                    )
                    try:
                        while True:
                            yield next(new_plan_str_gen)
                    except StopIteration as e:
                        new_plan_str = e.value
                    
                    new_plan = parse_json_string(new_plan_str.content)

                    yield PlanGenerationEnd(plan=new_plan, message="✅ New debugging plan generated.")
                    
                    plan = new_plan
                    step_index = 0
                    continue # 重置循环，从新计划的第一步开始
                except Exception as e:
                    yield TaskError(message=f"Failed to generate debugging plan: {e}", error_details=str(e))
                    return ExecutionResult(success=False, error_message=str(e))

            execution_context[f"step_{step_index + 1}_result"] = tool_result
            step_index += 1
        
        final_result_obj = execution_context.get(f"step_{len(plan)}_result")

        if final_result_obj and isinstance(final_result_obj, ExecutionResult) and final_result_obj.success:
            self.last_successful_script = final_result_obj.executed_script
            yield TaskEnd(success=True, final_message="🎉 Task completed successfully!", message = final_result_obj.executed_script)
        else:
            # If the task fails or doesn't end with a script, clear the last script
            self.last_successful_script = None 
            error_msg = final_result_obj.error_message if isinstance(final_result_obj, ExecutionResult) else str(final_result_obj)
            yield TaskEnd(success=False, final_message=f"❌ Task failed. Final status: {error_msg}", final_script=final_script)
        
        return final_result_obj
    
    def run_enhanced_coding_task(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """
        使用增强的plan/act模式执行编码任务
        """
        yield {"type": "status", "message": "🚀 Starting enhanced coding task..."}
        
        try:
            for update in self.enhanced_executor.execute_task(user_input):
                # 保存最后成功的脚本
                # 在任务成功结束时，从 final_result 中获取脚本
                if isinstance(update, TaskExecutionEnd) and update.success:
                    if update.final_result and update.final_result.executed_script:
                        self.last_successful_script = update.final_result.executed_script

                # 将状态更新原封不动地传递给上层
                yield update
                
        except Exception as e:
            if e is None:
                print("捕获到了 None 异常对象！")
                message = "Enhanced coding task failed: Unknown error (NoneType)"
            else:
                message = f"Enhanced coding task failed: {str(e)}"

            import traceback
            tb = traceback.format_exc()
            timestamp = datetime.datetime.now().isoformat()
            # 日志或调试信息
            print("=== Enhanced Coding Task Error ===")
            print(f"Time: {timestamp}")
      
            print(f"User Input: {user_input}")
            print(f"Message: {message}")
            print("Traceback:")
            print(tb)

            # 也可以写入日志文件
            with open("error_log.txt", "a") as f:
                f.write(f"[{timestamp}] : {message}\n{tb}\nUser Input: {user_input}\n\n")


            from agent.enhanced_executor_status import ExecutorError
            yield ExecutorError(
                message=message,
                error_details=tb
            )

    def run_spec_task(self, task_description: str) -> Generator[Dict[str, Any], None, None]:
        """
        Implements the structured spec development mode following the EARS methodology.
        
        Workflow:
        1. Requirements analysis and documentation (EARS format)
        2. Technical design documentation  
        3. Task breakdown and implementation planning
        
        Args:
            task_description: The initial task description from user
            
        Yields:
            Dictionary updates about the progress of the spec development
        """
        import re
        import time
        
        # Generate a spec name from the task description
        spec_name = re.sub(r'[^\w\s-]', '', task_description.lower())
        spec_name = re.sub(r'[-\s]+', '_', spec_name)[:50]
        timestamp = int(time.time())
        spec_name = f"{spec_name}_{timestamp}"
        
        yield {"type": "status", "message": f"🔍 Starting structured spec development mode for: {spec_name}"}
        
        # Create specs directory structure
        specs_dir = f"specs/{spec_name}"
        os.makedirs(specs_dir, exist_ok=True)
        
        # 1. Retrieve relevant context with RAG
        yield {"type": "status", "message": "Retrieving context from codebase..."}
        relevant_files = yield from self.rag.retrieve(task_description, top_k=5)
        context_str = "\n---\n".join(
            f"File: {doc.file_path}\n\n{doc.source_code}" for doc in relevant_files
        )
        
        # Phase 1: Requirements Analysis and Documentation
        yield {"type": "status", "message": "📋 Phase 1: 搞清楚问题和需求，生成需求文档..."}
        
        @llm.prompt()
        def generate_requirements_document(task: str, context: str):
            """
            你是一名高级业务分析师和需求工程师。分析用户的任务并使用 EARS（Easy Approach to Requirements Syntax）方法创建结构化需求文档。
            
            用户任务: {task}
            
            技术上下文:
            {context}
            
            请严格按照以下格式创建需求文档：
            
            # 需求文档
            
            ## 介绍
            
            [清楚地描述用户想要实现什么]
            
            ## 需求
            
            ### 需求 1 - [需求名称]
            
            **用户故事：** [从用户角度描述需求的用户故事]
            
            #### 验收标准
            
            1. While [可选前置条件], when [可选触发器], the [系统名称] shall [系统响应]
            2. [使用 EARS 格式的其他验收标准]
            3. [根据需要添加更多标准]
            
            ### 需求 2 - [如果需要的话添加更多需求]
            
            [根据需要继续添加更多需求]
            
            重点关注:
            - 清晰、可测试的验收标准
            - EARS 格式: While <前置条件>, when <触发器>, the <系统名称> shall <响应>
            - 功能性和非功能性需求
            - DolphinDB 特定考虑事项
            
            例如: "When 选择"静音"时，笔记本电脑应当抑制所有音频输出。"
            """
        
        requirements_doc = generate_requirements_document(task=task_description, context=context_str)
        requirements_path = f"{specs_dir}/requirements.md"
        
        # Save requirements document
        with open(requirements_path, 'w', encoding='utf-8') as f:
            f.write(requirements_doc)
        
        yield {
            "type": "requirements_document",
            "spec_name": spec_name,
            "content": requirements_doc,
            "file_path": requirements_path,
            "message": f"需求文档已生成并保存到 {requirements_path}"
        }
        
        # Wait for user confirmation
        yield {
            "type": "confirmation_request",
            "phase": "requirements",
            "message": "请审查需求文档。确认它准确捕获了您的需求后，我们将进入技术设计阶段。"
        }
        
        # Phase 2: Technical Design
        yield {"type": "status", "message": "🏗️ Phase 2: 根据确认的需求进行技术方案设计..."}
        
        @llm.prompt()
        def generate_design_document(task: str, requirements: str, context: str):
            """
            你是一名专门从事 DolphinDB 系统的高级软件架构师,你需要使用dolphindb脚本来完成用户需求。基于确认的需求创建技术设计文档。
            
            原始任务: {task}
            
            需求文档:
            {requirements}
            
            技术上下文:
            {context}
            
            请创建包含以下结构的技术设计文档：
            
            # 技术方案设计
            
            ## 概述
            [技术方法的简要概述]
            
            ## 架构设计
            [系统架构描述]
            
            ## 技术栈
            - 使用的 DolphinDB 版本和功能
            - 附加库或工具
            - 数据结构和算法
            
            ## 数据库设计
            [数据库模式、表、分区策略（如适用）]
            
            ## 接口设计
            [API 端点、函数签名、数据格式]
            
            ## 实施策略
            [逐步实施方法]
            
            ## 测试策略
            [如何测试实施]
            
            ## 安全性考虑
            [安全影响和措施]
            
            ## 性能考虑
            [性能影响和优化]
            
            在有助于架构或流程可视化的地方使用 mermaid 图表。
            """
        
        design_doc = generate_design_document(
            task=task_description,
            requirements=requirements_doc,
            context=context_str
        )
        design_path = f"{specs_dir}/design.md"
        
        # Save design document
        with open(design_path, 'w', encoding='utf-8') as f:
            f.write(design_doc)
        
        yield {
            "type": "design_document",
            "spec_name": spec_name,
            "content": design_doc,
            "file_path": design_path,
            "message": f"技术设计文档已创建并保存到 {design_path}"
        }
        
        # Wait for user confirmation
        yield {
            "type": "confirmation_request",
            "phase": "design",
            "message": "请审查技术设计文档。确认架构和方法后，我们将进入任务拆分阶段。"
        }
        
        # Phase 3: Task Breakdown
        yield {"type": "status", "message": "📝 Phase 3: 根据需求文档和技术方案进行任务拆分..."}
        
        @llm.prompt()
        def generate_task_breakdown(requirements: str, design: str):
            """
            你是一名高级项目经理和技术负责人。基于需求和设计文档创建详细的任务分解。
            
            需求:
            {requirements}
            
            设计:
            {design}
            
            请按照以下格式创建实施计划：
            
            # 实施计划
            
            ## 任务列表
            
            - [ ] 1. [任务标题]
              - 具体要做的事情: [需要做什么的详细描述]
              - 预估时间: [预估时间]
              - 依赖: [对其他任务的依赖]
              - 需求: [相关需求编号]
              - 验收标准: [如何验证完成]
            
            - [ ] 2. [下一个任务]
              - 具体要做的事情: [描述]
              - 预估时间: [时间估计]
              - 依赖: [依赖关系]
              - 需求: [需求]
              - 验收标准: [验收标准]
            
            [继续所有必要的任务]
            
            ## 实施顺序
            [推荐的实施顺序及理由]
            
            重点关注:
            - 逻辑任务分解
            - 清晰的依赖关系
            - 可测试的交付物
            - 增量开发方法
            """
        
        tasks_doc = generate_task_breakdown(
            requirements=requirements_doc,
            design=design_doc
        )
        tasks_path = f"{specs_dir}/tasks.md"
        
        # Save tasks document
        with open(tasks_path, 'w', encoding='utf-8') as f:
            f.write(tasks_doc)
        
        yield {
            "type": "tasks_document",
            "spec_name": spec_name,
            "content": tasks_doc,
            "file_path": tasks_path,
            "message": f"实施任务分解已完成并保存到 {tasks_path}"
        }
        
        # Wait for user confirmation
        yield {
            "type": "confirmation_request",
            "phase": "tasks",
            "message": "请审查任务分解。确认实施计划后，您可以开始正式执行任务。"
        }
        
        # Final summary
        yield {
            "type": "final_result",
            "success": True,
            "spec_name": spec_name,
            "requirements_path": requirements_path,
            "design_path": design_path,
            "tasks_path": tasks_path,
            "message": "结构化规范开发工作流程已成功完成！所有文档已保存到 specs 目录。"
        }

    def save_last_script(self, file_path: str) -> Tuple[bool, str]:
        """
        Saves the last successfully executed script to a file.
        
        Returns:
            A tuple of (success: bool, message: str).
        """
        if not self.last_successful_script:
            return False, "No successful script is available to save. Please run a /code task first."
        
        try:
            # Create directories if they don't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.last_successful_script)
            
            return True, f"Script successfully saved to: {file_path}"
        except Exception as e:
            return False, f"Error saving file: {e}"