# file: agent/enhanced_planner.py

from typing import List, Dict, Any, Optional, Generator
from dataclasses import dataclass, field
from enum import Enum
import json
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


@dataclass
class ExecutionPlan:
    task_description: str
    complexity: TaskComplexity
    steps: List[PlanStep]
    current_step: int = 0
    context: Dict[str, Any] = field(default_factory=dict)
    
    def get_next_executable_step(self) -> Optional[PlanStep]:
        """获取下一个可执行的步骤"""
        for step in self.steps[self.current_step:]:
            if step.status == StepStatus.PENDING:
                # 检查依赖是否满足
                if all(self.steps[dep_id-1].status == StepStatus.SUCCESS 
                      for dep_id in step.dependencies):
                    return step
        return None
    
    def mark_step_completed(self, step_id: int, success: bool, result: Any = None, error: str = None):
        """标记步骤完成状态"""
        step = self.steps[step_id - 1]
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
    def _generate_initial_plan(self, task_description: str, complexity: str, 
                              available_tools: str, rag_context: str) -> str:
        """
        You are an expert DolphinDB task planner. Create a detailed execution plan.
        
        ## Task Description
        {{ task_description }}
        
        ## Task Complexity
        {{ complexity }}
        
        ## Available Tools
        {{ available_tools }}
        
        ## Relevant Context
        {{ rag_context }}
        
        ## Planning Guidelines
        
        For SIMPLE tasks:
        - Start with environment inspection if needed
        - Execute the main operation
        - Validate results
        
        For MEDIUM tasks:
        - Inspect environment and gather requirements
        - Prepare data or setup environment
        - Execute main operations in logical sequence
        - Validate and format results
        
        For COMPLEX tasks:
        - Break down into logical phases
        - Include validation steps between phases
        - Plan for potential error scenarios
        - Include result verification and optimization
        
        ## Output Format
        Return a JSON array of steps with this structure:
        ```json
        [
          {
            "step_id": 1,
            "action": "tool_name",
            "args": {"param": "value"},
            "thought": "Why this step is needed",
            "dependencies": []
          }
        ]
        ```

        注意，输出的时候，不要有额外的开头，必须保证是以```json开头，```结束的json格式
        
        ## Available Actions
        Use only the tool names from the available tools list above.
        """
        pass
    
    @llm.prompt(model="deepseek")
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
        """
        pass
    
    def create_execution_plan(self, task_description: str) -> ExecutionPlan:
        """创建执行计划"""
        # 1. 获取相关上下文
        rag_context = self._get_rag_context(task_description)
        
        # 2. 分析任务复杂度
        available_tools = json.dumps(self.tool_manager.get_tool_definitions(), indent=2)
        complexity_str = self._analyze_task_complexity(task_description, available_tools)
        complexity = TaskComplexity(complexity_str.lower())
        
        # 3. 生成初始计划
        plan_json = self._generate_initial_plan(
            task_description=task_description,
            complexity=complexity_str,
            available_tools=available_tools,
            rag_context=rag_context
        )
        
        # 4. 解析计划
        plan_data = parse_json_string(plan_json)
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
            complexity=complexity,
            steps=steps
        )
    
    def handle_step_failure(self, plan: ExecutionPlan, failed_step: PlanStep) -> ExecutionPlan:
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
        
        execution_context = json.dumps(plan.context, indent=2)
        
        # 生成恢复计划
        recovery_json = self._replan_after_failure(
            original_plan=original_plan_json,
            failed_step=failed_step_json,
            error_message=failed_step.error_message or "Unknown error",
            execution_context=execution_context
        )
        
        recovery_data = parse_json_string(recovery_json)
        
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
    
    def _get_rag_context(self, task_description: str) -> str:
        """获取RAG上下文"""
        try:
            relevant_docs = self.rag_system.retrieve(task_description, top_k=3)
            return "\n---\n".join(
                f"File: {doc.file_path}\n\n{doc.source_code}" 
                for doc in relevant_docs
            )
        except Exception:
            return "No relevant context found."