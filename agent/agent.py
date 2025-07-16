# file: ddb_agent/agent.py (之前在main.py中虚构的，现在正式实现)

import json
import os
from typing import Generator, List, Dict, Any, Tuple
from agent.code_executor import CodeExecutor
from agent.coding_task_state import CodingTaskState
from agent.execution_result import ExecutionResult
from agent.prompts import debugging_planner, fix_script_from_error, generate_initial_script
from llm.llm_client import LLMResponse
from session.session_manager import SessionManager
from context.context_builder import ContextBuilder
from rag.rag_entry import DDBRAG
from llm.llm_prompt import llm # 假设llm实例在这里

from rich.pretty import pprint

from agent.tool_manager import ToolManager
from agent.tools.ddb_tools import GetFunctionSignatureTool, RunDolphinDBScriptTool
from agent.tools.enhanced_ddb_tools import (
    InspectDatabaseTool, ListTablesTool, DescribeTableTool, 
    ValidateScriptTool, QueryDataTool, CreateSampleDataTool, OptimizeQueryTool
)
from agent.enhanced_planner import EnhancedPlanner
from agent.enhanced_executor import EnhancedExecutor
from utils.json_parser import parse_json_string


class DDBAgent:
    """
    The main agent orchestrating all components: session, RAG, context, and LLM.
    """
    def __init__(self, project_path: str, model_name: str, max_window_size: int):
        self.project_path = project_path
        self.session_manager = SessionManager(project_path=project_path)
        self.context_builder = ContextBuilder(model_name=model_name, max_window_size=max_window_size)
        self.rag = DDBRAG(project_path=project_path)
        self.llm_model_name = model_name
        self.code_executor = CodeExecutor()
        # 初始化工具管理器（包含增强工具集）
        self.tool_manager = ToolManager([
            # 基础工具
            RunDolphinDBScriptTool(),
            GetFunctionSignatureTool(),
            # 增强工具集
            InspectDatabaseTool(),
            ListTablesTool(),
            DescribeTableTool(),
            ValidateScriptTool(),
            QueryDataTool(),
            CreateSampleDataTool(),
            OptimizeQueryTool()
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
            # 这个函数只用于传递历史，所以返回空字典
            return {"model": self.llm_model_name}
        
        self.chat_prompt_func = _default_chat_prompt

    def start_new_session(self):
        """Starts a new chat session."""
        self.session_manager.new_session()

    @llm.prompt(stream=True)
    def _streaming_chat_prompt(self, conversation_history: List[Dict[str, str]]):
        """       You are a helpful DolphinDB assistant. Continue the conversation naturally.
        The user's latest message is the last one in the history.
        """
    
    def _stream_wrapper(self, generator):
        """一个包装器，用于在流式输出结束后保存历史记录。"""
        full_content = ""
        final_meta = None
        for part in generator:
            if isinstance(part, str):
                full_content += part
                yield part # 将文本块传递出去
            elif isinstance(part, LLMResponse):
                final_meta = part
        
        # 流结束后，保存完整对话
        if final_meta and final_meta.success:
            self.session_manager.add_message('assistant', full_content)
            self.session_manager.save_session()
        
        # 将最后的元数据也传递出去，以便上层检查错误
        #if final_meta:
        #    yield final_meta

    def run_task(self, user_input: str, task_type: str = 'chat', stream: bool = False) :
        """
        Handles a user request by orchestrating RAG, context building, and LLM interaction.
        """
        # 1. 更新会话历史
        self.session_manager.add_message('user', user_input)
        full_conversation_history = self.session_manager.get_history()

        # 2. 使用 RAG 检索相关文件上下文
        # 我们用最新的用户输入去检索
        relevant_files = self.rag.retrieve(user_input, top_k=5)

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
        
        # 5. 调用 LLM
        # 这里我们不再使用简单的 chat_oai，而是利用我们之前设计的 llm.prompt 框架
        # 来调用一个带有完整、剪枝后历史的 prompt 函数。
        # 注意：这里我们不再需要一个复杂的模板，因为所有上下文都已在 message 列表中。
        # 我们只需一个简单的函数来触发调用。

        if stream:
            response_generator = self._streaming_chat_prompt(
                conversation_history=final_messages
            )
            return self._stream_wrapper(response_generator)
        else:
            assistant_response = self.chat_prompt_func(
                conversation_history=final_messages
            )

        # 6. 更新会话并保存
        self.session_manager.add_message('assistant', assistant_response)
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
    
    def run_coding_task_with_planner(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """
        Orchestrates the plan-and-execute loop for a coding task, yielding state updates.
        """
        yield {"type": "status", "message": "Starting new PLAN-and-EXECUTE coding task..."}


        # 2. 生成初始计划
        yield {"type": "status", "message": "Generating initial plan..."}
        # 这里我们简化，直接生成一个包含run_dolphindb_script的计划
        # 实际中可能需要一个Planner来生成
        try:
            initial_script = generate_initial_script(user_query=user_input, rag_context="...") # 假设有rag_context
            plan = [
                {
                    "step": 1, 
                    "thought": "I will start by generating a script to address the user's request and then execute it.", 
                    "action": "run_dolphindb_script", 
                    "args": {"script": initial_script}
                }
            ]
            yield {"type": "plan", "plan": plan, "message": "Initial plan generated."}
        except Exception as e:
            yield {"type": "error", "message": f"Failed to generate initial script: {e}"}
            return

        # 3. 执行计划循环
        step_index = 0
        execution_context = {}

        while step_index < len(plan):
            current_step = plan[step_index]
            action = current_step["action"]
            args = current_step["args"]
            thought = current_step["thought"]
            
            # Yield 当前步骤的思考过程
            yield {"type": "step_start", "step": step_index + 1, "thought": thought, "action": action, "args": args}

            # 执行工具调用
            tool_result = self.tool_manager.call_tool(action, args)

            is_success = True
            if isinstance(tool_result, ExecutionResult):
                observation_str = str(tool_result.data) if tool_result.success else f"Execution failed. Error:\n{tool_result.error_message}"
                is_success = tool_result.success
            else: # It's a string from another tool like get_function_signature
                observation_str = str(tool_result)

            yield {"type": "step_result", "step": step_index + 1, "observation": observation_str}

            
            # 检查是否需要启动调试子流程
            if action == "run_dolphindb_script" and  not is_success:
                yield {"type": "status", "message": "Execution failed. Entering debugging sub-task..."}
                
                failed_code = args["script"]
                error_message = observation_str.split("Error:\n", 1)[1]
                tool_defs_str = json.dumps(self.tool_manager.get_tool_definitions(), indent=2)

                try:
                    # 调用调试Planner
                    new_plan_str = debugging_planner(
                        original_query=user_input,
                        failed_code=failed_code,
                        error_message=error_message,
                        tool_definitions=tool_defs_str
                    )
                    new_plan = parse_json_string(new_plan_str)

                    # Yield 新的调试计划
                    yield {"type": "plan", "plan": new_plan, "message": "Generated a new debugging plan."}
                    
                    plan = new_plan
                    step_index = 0
                    continue # 重置循环，从新计划的第一步开始
                except Exception as e:
                    yield {"type": "error", "message": f"Failed to generate debugging plan: {e}"}
                    return

            execution_context[f"step_{step_index + 1}_result"] = tool_result
            step_index += 1
        
        final_result_obj = execution_context.get(f"step_{len(plan)}_result")

        if final_result_obj and isinstance(final_result_obj, ExecutionResult) and final_result_obj.success:
            self.last_successful_script = final_result_obj.executed_script 
        else:
            # If the task fails or doesn't end with a script, clear the last script
            self.last_successful_script = None 

        yield {"type": "final_result", "result_object": final_result_obj}
    
    def run_enhanced_coding_task(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """
        使用增强的plan/act模式执行编码任务
        """
        yield {"type": "status", "message": "🚀 Starting enhanced coding task..."}
        
        try:
            # 使用增强执行器执行任务
            for update in self.enhanced_executor.execute_task(user_input):
                # 保存最后成功的脚本
                if (update.get("type") == "final_result" and 
                    update.get("result_object") and 
                    isinstance(update["result_object"], ExecutionResult) and 
                    update["result_object"].success):
                    self.last_successful_script = update["result_object"].executed_script
                
                yield update
                
        except Exception as e:
            yield {
                "type": "error", 
                "message": f"Enhanced coding task failed: {str(e)}"
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