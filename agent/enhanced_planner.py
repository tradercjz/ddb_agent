# file: agent/enhanced_planner.py

import logging
from typing import List, Dict, Any, Optional, Generator, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json

import numpy as np
import pandas as pd
from agent.enhanced_planner_status import AnyPlannerStatus, ComplexityAnalysisEnd, ComplexityAnalysisStart, InitialPlanGenerationStart, PlannerError, RAGContextEnd, RAGContextStart
from agent.execution_result import ExecutionResult
from llm.llm_prompt import llm
from utils.json_parser import parse_json_string


class TaskComplexity(Enum):
    SIMPLE = "simple"      # 单步任务，如简单查询
    MEDIUM = "medium"      # 多步任务，需要数据准备
    COMPLEX = "complex"    # 复杂任务，需要多轮迭代


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    step_id: int
    action: str
    args: Dict[str, Any]
    thought: str
    dependencies: List[int] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2

# 设置日志记录器
logging.basicConfig(
    filename='execution_errors.log',  # 日志文件的名称
    level=logging.ERROR,  # 记录错误及更严重的日志
    format='%(asctime)s - %(levelname)s - %(message)s'  # 日志格式
)
@dataclass
class ExecutionPlan:
    task_description: str
    steps: List[PlanStep]
    current_step: int = 0
    context: Dict[str, Any] = field(default_factory=dict)
    complexity: Optional[TaskComplexity] = TaskComplexity('simple')
    
    def get_next_executable_step(self) -> Optional[PlanStep]:
        """获取下一个可执行的步骤"""
        for step in self.steps[self.current_step:]:
            if step.status == StepStatus.PENDING:
                #TODO：注意这里是否存在问题
                try:

                    if step.dependencies:
                        # 确保索引合法
                        if all(self.steps[dep_id - 1].status == StepStatus.SUCCESS for dep_id in step.dependencies):
                            return step
                    else:
                        return step
                except IndexError as e:
                    # 异常处理，输出错误信息
                    print(f"IndexError: Invalid index while checking step dependencies for step {step}")
                    print(f"Step information: {step}")
                    print(f"Dependencies: {step.dependencies}")
                    print(f"Error details: {e}")

                    logging.error(f"IndexError: Invalid index while checking step dependencies for step {step}")
                    logging.error(f"Step information: {step}")
                    logging.error(f"Dependencies: {step.dependencies}")
                    logging.error(f"Error details: {e}")

                    
                    
                    continue
        return None
    
    def mark_step_completed(self, step_id: int, success: bool, result: Any = None, error: str = None):
        """标记步骤完成状态"""
        
        step = None
        for s in self.steps:
            if s.step_id == step_id:
                step = s
                break
        step.status = StepStatus.SUCCESS if success else StepStatus.FAILED
        step.result = result
        step.error_message = error
    
    def can_continue(self) -> bool:
        """检查是否可以继续执行"""
        return any(step.status in [StepStatus.PENDING, StepStatus.FAILED] 
                  and step.retry_count < step.max_retries 
                  for step in self.steps)


class EnhancedPlanner:
    """增强的任务规划器"""
    
    def __init__(self, tool_manager, rag_system):
        self.tool_manager = tool_manager
        self.rag_system = rag_system
    
    @llm.prompt(model="deepseek")
    def _analyze_task_complexity(self, task_description: str, available_tools: str) -> str:
        """
        Analyze the complexity of a given task and categorize it.
        
        Task: {{ task_description }}
        
        Available Tools: {{ available_tools }}
        
        Analyze this task and determine its complexity level:
        - SIMPLE: Can be completed in 1-2 steps with basic operations
        - MEDIUM: Requires 3-5 steps, may need data preparation or validation
        - COMPLEX: Requires 6+ steps, multiple iterations, or complex logic
        
        Return only one of: SIMPLE, MEDIUM, COMPLEX
        """
        pass
    
    @llm.prompt(model="deepseek")
    def _generate_initial_plan(self, task_description: str,
                              available_tools: str, rag_context: str) -> str:
        """
        You are an expert DolphinDB automation engineer. Your goal is to create a step-by-step execution plan to accomplish the user's task. You must think iteratively and use the available tools to break down the problem.
        当涉及到文件系统操作时候，不要用dolphindb的脚本来操作文件系统，而是使用MCP工具来处理文件系统操作

        ## Primary Goal
        {{ task_description }}

        ## Available Tools
        You have access to a set of tools. You must choose the most appropriate tool for each step.
        ```json
        {{ available_tools }}
        ```

        ### Key Tool Explanations:
        - **run_dolphindb_script**: Use this to execute DolphinDB code. This should often be the final step after preparing data or the environment. Do not use it for simple queries if a more specific tool like `query_data` exists.
        - **get_function_documentation**: If you encounter an error with a DolphinDB function or are unsure of its usage, use this tool to get help before attempting to fix the code.
        - **filesystem.read_file / filesystem.write_file**: These are MCP tools. Use them when you need to read external data files (like CSVs) or write results to a file on the local system.
        - **Other MCP tools (e.g., `filesystem.*`)**: These tools allow you to interact with the local environment. Use them for tasks that are not directly related to DolphinDB execution, such as listing files to find data, or creating directories.

        ## Relevant Context from Knowledge Base
        {{ rag_context }}

        ## Planning Guidelines & Thought Process
        1.  **Understand the Goal**: What is the user's final objective?
        2.  **Information Gathering**: Do I have all the information I need? Do I need to check if a file exists first (`filesystem.list_files`)? Do I need to read a schema (`describe_table`)?
        3.  **Environment Preparation**: Does a table need to be created (`create_sample_data` or `run_dolphindb_script`)? Does a file need to be created on disk (`filesystem.write_file`)?
        4.  **Core Logic Execution**: Now, execute the main part of the task, which might be running a complex DolphinDB script (`run_dolphindb_script`) or querying data (`query_data`).
        5.  **Result Handling**: What should be done with the result? Should it be written to a file (`filesystem.write_file`)?

        ## Output Format
        Your response MUST be a valid JSON array of steps. Each step must be an object with the following keys:
        - `step_id`: A sequential integer starting from 1.
        - `action`: The name of the tool to use from the "Available Tools" list.
        - `args`: An object containing the parameters for the chosen tool.
        - `thought`: Your detailed reasoning for this step. Explain WHY you are taking this action and what you expect to achieve.
        - `dependencies`: A list of `step_id`s that must be completed successfully before this step can run. An empty list `[]` means no dependencies.

        ### Example Plan Structure:
        ```json
        [
          {
            "step_id": 1,
            "thought": "First, I need to check what files are in the '/data' directory to find the correct CSV file the user mentioned.",
            "action": "filesystem.list_files",
            "args": {
              "path": "/data"
            },
            "dependencies": []
          },
          {
            "step_id": 2,
            "thought": "Now that I have the filename, I'll create a DolphinDB script to load this CSV into a table and then perform a calculation.",
            "action": "run_dolphindb_script",
            "args": {
              "script": "t = loadText('/data/trades.csv'); select avg(price) from t"
            },
            "dependencies": [1]
          }
        ]
        ```

        ## Important Rules
        - **Tool First**: Always prefer using a specific tool over writing a script if a tool can accomplish the sub-task.
        - **DolphinDB Specifics**: Remember that DolphinDB has distributed tables (DFS) which need `loadTable`, and in-memory tables which do not.
        - **SQL Syntax**: In DolphinDB SQL, `select top N ...` is used for limiting results. Do not use `LIMIT`.

        Now, create the execution plan for the user's request.
        """
        pass
    
    @llm.prompt(model="gemini-2.5-pro")
    def _replan_after_failure(self, original_plan: str, failed_step: str, 
                             error_message: str, execution_context: str) -> str:
        """
        A step in the execution plan has failed. Analyze the failure and create a recovery plan.
        
        ## Original Plan
        {{ original_plan }}
        
        ## Failed Step
        {{ failed_step }}
        
        ## Error Message
        {{ error_message }}
        
        ## Current Execution Context
        {{ execution_context }}
        
        ## Your Task
        1. Analyze why the step failed
        2. Determine if the failure can be recovered from
        3. Generate a new plan that either:
           - Fixes the failed step and continues
           - Takes an alternative approach
           - Gracefully handles the failure

        如果遇到变量已经定义的，切不是这一次定义的话，那可以使用undef函数
        sql要筛选条数数据的话，有limit就行，no top clause, no top clause，不要加上top语句
        
        Return a JSON object with:
        ```json
        {
          "recovery_strategy": "fix_and_continue|alternative_approach|graceful_failure",
          "analysis": "Why the step failed and how to recover",
          "new_steps": [
            {
              "step_id": 1,
              "action": "tool_name", 
              "args": {"param": "value"},
              "thought": "Recovery reasoning",
              "dependencies": []
            }
          ]
        }
        ```

        注意，输出的时候，不要有额外的开头，必须保证是以```json开头，```结束的json格式
        注意，DolphinDB有分布式表和内存表。内存表，不需要使用loadTable来加载，只有dfs表需要
        """
        pass
    
    def create_execution_plan(self, task_description: str) -> Generator[ExecutionPlan, Dict[str, Any], None]:
        """创建执行计划"""
        # 1. 获取相关上下文
        try:
            # yield RAGContextStart(message="Retrieving RAG context...")
            # rag_context_gen = self._get_rag_context(task_description)
            # try:
            #     while True:
            #         rag_status = next(rag_context_gen)
            #         yield rag_status 
            # except StopIteration as e:
            #     rag_context = e.value # _get_rag_context 返回最终的字符串
            # yield RAGContextEnd(message="RAG context retrieved.", context=rag_context)
            
            # 2. 分析任务复杂度
            # yield ComplexityAnalysisStart(message="Analyzing task complexity...")
            available_tools = json.dumps(self.tool_manager.get_tool_definitions(), indent=2)
            # complexity_str_gen = self._analyze_task_complexity(task_description, available_tools)
            # try:
            #     while True:
            #         next(complexity_str_gen)
            # except StopIteration as e:
            #     complexity_str = e.value
            # complexity = TaskComplexity(complexity_str.content.lower())
            # yield ComplexityAnalysisEnd(message=f"Task complexity: {complexity.value.upper()}", complexity=complexity.value)
                
            # 3. 生成初始计划
            yield InitialPlanGenerationStart(message="Generating initial plan from LLM...")
            plan_json_gen = self._generate_initial_plan(
                task_description=task_description,
                available_tools=available_tools,
                rag_context=""
            )

            try:
                while True:
                    yield next(plan_json_gen)
            except StopIteration as e:
                plan_json = e.value

            yield {
                "type": "planner_info",
                "subtype": "llm_prompt",
                "content": plan_json,
                "message": "Generated prompt for plan generation."
            }
            
            # 4. 解析计划
            plan_data = parse_json_string(plan_json.content)

            if plan_data is None:
                raise ValueError("无法创建执行计划，请再试一次")
            steps = [
                PlanStep(
                    step_id=step["step_id"],
                    action=step["action"],
                    args=step["args"],
                    thought=step["thought"],
                    dependencies=step.get("dependencies", [])
                )
                for step in plan_data
            ]
            
            return ExecutionPlan(
                task_description=task_description,
                complexity="",
                steps=steps
            )
        
        except Exception as e:
            error_details = f"{type(e).__name__}: {e}"
            yield PlannerError(message="An error occurred during planning.", error_details=error_details)
    
   
    
    def handle_step_failure(self, plan: ExecutionPlan, failed_step: PlanStep) -> Generator[AnyPlannerStatus, None, ExecutionPlan]:
        """处理步骤失败，生成恢复计划"""
        # 准备上下文信息
        original_plan_json = json.dumps([
            {
                "step_id": step.step_id,
                "action": step.action,
                "args": step.args,
                "thought": step.thought,
                "status": step.status.value
            }
            for step in plan.steps
        ], indent=2)
        
        failed_step_json = json.dumps({
            "step_id": failed_step.step_id,
            "action": failed_step.action,
            "args": failed_step.args,
            "thought": failed_step.thought,
            "error": failed_step.error_message
        }, indent=2)
        
        def custom_serializer(obj):
            if isinstance(obj, np.ndarray):
                # 将 numpy 数组转换为 python 列表
                return obj.tolist()
            if isinstance(obj, np.datetime64):
                return pd.Timestamp(obj).isoformat()
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                 # 将 DataFrame 转换为 JSON 字符串（记录导向）
                 # orient='records' -> [{'col1': val1, 'col2': val2}, ...]
                 # orient='split' -> {'columns': [...], 'index': [...], 'data': [[...], [...]]}
                 # 'split' 格式通常更紧凑
                return obj.to_json(orient='split', date_format='iso')
            elif isinstance(obj, ExecutionResult):
                return obj.dict()  # Convert ExecutionResult to dict
            elif isinstance(obj, pd.DataFrame):
                return obj.to_dict(orient="records")  # 常用于 JSON 结构
            raise TypeError(f'Object of type {obj.__class__.__name__} is not serializable')
        
        execution_context = json.dumps(plan.context, indent=2, default=custom_serializer)
   
        # 生成恢复计划
        recovery_json_gen = self._replan_after_failure(
            original_plan=original_plan_json,
            failed_step=failed_step_json,
            error_message=failed_step.error_message or "Unknown error",
            execution_context=execution_context
        )

        try:
            while True:
                yield(next(recovery_json_gen))
        except StopIteration as e:
            recovery_json = e.value
        
        recovery_data = parse_json_string(recovery_json.content)

        if recovery_data is None or "recovery_strategy" not in recovery_data:
            # 如果解析失败或返回的数据结构不符合预期
            error_msg = (
                "Failed to generate a valid recovery plan from LLM. "
                f"The model's response was either not valid JSON or lacked the required 'recovery_strategy' key. "
                f"Raw response was: {recovery_json}"
            )
            # 我们可以选择抛出一个更明确的异常，或者让 Agent 放弃
            print(f"CRITICAL: {error_msg}")
            # 标记失败步骤为不可恢复，并返回原计划，让执行器知道任务失败
            failed_step.status = StepStatus.FAILED 
            failed_step.error_message = f"{failed_step.error_message}\n\n[Planner Error]: {error_msg}"
            failed_step.retry_count = failed_step.max_retries # 标记为无法重试
            return plan # 返回原计划，让 executor 终止
        
        # 根据恢复策略更新计划
        if recovery_data["recovery_strategy"] == "fix_and_continue":
            # 替换失败的步骤及后续步骤
            new_steps = [
                PlanStep(
                    step_id=len(plan.steps) + i + 1,  # 新的步骤ID
                    action=step["action"],
                    args=step["args"],
                    thought=step["thought"],
                    dependencies=step.get("dependencies", [])
                )
                for i, step in enumerate(recovery_data["new_steps"])
            ]
            
            # 保留成功的步骤，添加新的恢复步骤
            successful_steps = [s for s in plan.steps if s.status == StepStatus.SUCCESS]
            plan.steps = successful_steps + new_steps
            plan.current_step = len(successful_steps)
        
        return plan
    
    def _get_rag_context(self, task_description: str) -> Generator[Dict[str, Any],str, None]:
        """获取RAG上下文"""
        try:
            relevant_docs = yield from self.rag_system.retrieve(task_description, top_k=3)
            return "\n---\n".join(
                f"File: {doc.file_path}\n\n{doc.source_code}" 
                for doc in relevant_docs
            )
        except Exception:
            return "No relevant context found."