# file: agent/enhanced_executor.py

from typing import Generator, Dict, Any, Optional
import time
import json
from dataclasses import asdict

from agent.enhanced_planner import EnhancedPlanner, ExecutionPlan, StepStatus
from agent.tool_manager import ToolManager
from agent.execution_result import ExecutionResult
from utils.logger import setup_llm_logger


class EnhancedExecutor:
    """增强的执行引擎，支持复杂的plan/act循环"""
    
    def __init__(self, tool_manager: ToolManager, planner: EnhancedPlanner, logger=None):
        self.tool_manager = tool_manager
        self.planner = planner
        self.logger = logger or setup_llm_logger()
        
        # 执行统计
        self.execution_stats = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_steps": 0,
            "failed_steps": 0,
            "recovery_attempts": 0
        }
    
    def execute_task(self, task_description: str) -> Generator[Dict[str, Any], None, None]:
        """执行任务，返回执行过程的状态更新"""
        self.execution_stats["total_tasks"] += 1
        
        yield {"type": "status", "message": "🚀 Starting enhanced plan-and-execute task..."}
        
        try:
            # 1. 创建执行计划
            yield {"type": "status", "message": "🧠 Analyzing task and creating execution plan..."}
            plan = self.planner.create_execution_plan(task_description)
            
            yield {
                "type": "plan", 
                "plan": [asdict(step) for step in plan.steps],
                "complexity": plan.complexity.value,
                "message": f"📋 Created {plan.complexity.value} execution plan with {len(plan.steps)} steps"
            }
            
            # 2. 执行计划
            final_result = None
            execution_start_time = time.time()
            
            while plan.can_continue():
                next_step = plan.get_next_executable_step()
                if not next_step:
                    break
                
                self.execution_stats["total_steps"] += 1
                
                # 执行步骤
                step_result = yield from self._execute_step(plan, next_step)
                
                if step_result["success"]:
                    plan.mark_step_completed(
                        next_step.step_id, 
                        True, 
                        step_result["result"]
                    )
                    
                    # 更新执行上下文
                    plan.context[f"step_{next_step.step_id}_result"] = step_result["result"]
                    
                    # 如果是最后一步，保存最终结果
                    if next_step.step_id == len(plan.steps):
                        final_result = step_result["result"]
                
                else:
                    # 步骤失败处理
                    self.execution_stats["failed_steps"] += 1
                    plan.mark_step_completed(
                        next_step.step_id, 
                        False, 
                        error=step_result["error"]
                    )
                    
                    # 尝试恢复
                    if next_step.retry_count < next_step.max_retries:
                        yield from self._handle_step_failure(plan, next_step)
                    else:
                        yield {
                            "type": "error",
                            "message": f"❌ Step {next_step.step_id} failed after {next_step.max_retries} retries: {step_result['error']}"
                        }
                        break
            
            # 3. 任务完成
            execution_time = time.time() - execution_start_time
            
            if final_result and isinstance(final_result, ExecutionResult) and final_result.success:
                self.execution_stats["successful_tasks"] += 1
                yield {
                    "type": "final_result",
                    "result_object": final_result,
                    "execution_time": execution_time,
                    "stats": self.execution_stats.copy(),
                    "message": f"✅ Task completed successfully in {execution_time:.2f}s"
                }
            else:
                self.execution_stats["failed_tasks"] += 1
                yield {
                    "type": "error",
                    "message": f"❌ Task failed after {execution_time:.2f}s",
                    "stats": self.execution_stats.copy()
                }
        
        except Exception as e:
            self.execution_stats["failed_tasks"] += 1
            yield {
                "type": "error",
                "message": f"💥 Unexpected error during task execution: {str(e)}"
            }
    
    def _execute_step(self, plan: ExecutionPlan, step) -> Generator[Dict[str, Any], None, None]:
        """执行单个步骤"""
        step.status = StepStatus.RUNNING
        
        yield {
            "type": "step_start",
            "step": step.step_id,
            "action": step.action,
            "thought": step.thought,
            "args": step.args,
            "message": f"▶️ Executing step {step.step_id}: {step.action}"
        }
        
        try:
            # 调用工具
            start_time = time.time()
            tool_result = self.tool_manager.call_tool(step.action, step.args)
            execution_time = time.time() - start_time
            
            # 分析结果
            if isinstance(tool_result, ExecutionResult):
                success = tool_result.success
                result_data = tool_result.data if success else tool_result.error_message
                observation = str(result_data)
            else:
                success = True
                result_data = tool_result
                observation = str(tool_result)
            
            yield {
                "type": "step_result",
                "step": step.step_id,
                "success": success,
                "observation": observation,
                "execution_time": execution_time,
                "message": f"{'✅' if success else '❌'} Step {step.step_id} {'completed' if success else 'failed'}"
            }
            
            return {
                "success": success,
                "result": tool_result,
                "error": None if success else str(result_data)
            }
        
        except Exception as e:
            error_msg = f"Tool execution error: {str(e)}"
            yield {
                "type": "step_result",
                "step": step.step_id,
                "success": False,
                "observation": error_msg,
                "message": f"❌ Step {step.step_id} failed with exception"
            }
            
            return {
                "success": False,
                "result": None,
                "error": error_msg
            }
    
    def _handle_step_failure(self, plan: ExecutionPlan, failed_step) -> Generator[Dict[str, Any], None, None]:
        """处理步骤失败"""
        self.execution_stats["recovery_attempts"] += 1
        
        yield {
            "type": "status",
            "message": f"🔧 Step {failed_step.step_id} failed, attempting recovery..."
        }
        
        try:
            # 生成恢复计划
            recovery_plan = self.planner.handle_step_failure(plan, failed_step)
            
            yield {
                "type": "recovery_plan",
                "original_step": failed_step.step_id,
                "new_steps": [asdict(step) for step in recovery_plan.steps[len(plan.steps):]],
                "message": f"🔄 Generated recovery plan with {len(recovery_plan.steps) - len(plan.steps)} new steps"
            }
            
            # 更新计划
            plan.steps = recovery_plan.steps
            plan.current_step = recovery_plan.current_step
            
        except Exception as e:
            yield {
                "type": "error",
                "message": f"🚨 Recovery planning failed: {str(e)}"
            }
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """获取执行统计信息"""
        stats = self.execution_stats.copy()
        if stats["total_tasks"] > 0:
            stats["success_rate"] = stats["successful_tasks"] / stats["total_tasks"]
        if stats["total_steps"] > 0:
            stats["step_failure_rate"] = stats["failed_steps"] / stats["total_steps"]
        return stats
    
    def reset_stats(self):
        """重置统计信息"""
        self.execution_stats = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_steps": 0,
            "failed_steps": 0,
            "recovery_attempts": 0
        }