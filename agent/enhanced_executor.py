# file: agent/enhanced_executor.py

import logging
from typing import Generator, Dict, Any, Optional, Tuple
import time
import json
from dataclasses import asdict

from agent.enhanced_planner import EnhancedPlanner, ExecutionPlan, PlanStep, StepStatus
from agent.tool_manager_enhanced import EnhancedToolManager
from agent.execution_result import ExecutionResult
from utils.logger import setup_llm_logger
from agent.enhanced_executor_status import (
    AnyExecutorStatus, ExecutorStatusUpdate, TaskExecutionStart, PlanGenerationStart,
    PlanGenerationEnd, StepExecutionStart, StepExecutionEnd, ExecutorError,
    RecoveryPlanStart, RecoveryPlanEnd, TaskExecutionEnd, FinalScriptExtracted
)

class EnhancedExecutor:
    """增强的执行引擎，支持复杂的plan/act循环"""
    
    def __init__(self, tool_manager: EnhancedToolManager, planner: EnhancedPlanner, logger=None):
        self.tool_manager = tool_manager
        self.planner = planner
        self.logger = logger or setup_llm_logger("app.log")
        
        # 执行统计
        self.execution_stats = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_steps": 0,
            "failed_steps": 0,
            "recovery_attempts": 0
        }
    
    def execute_task(self, task_description: str) -> Generator[AnyExecutorStatus, None, None]:
        """执行任务，返回执行过程的状态更新"""
        self.execution_stats["total_tasks"] += 1
        
        yield TaskExecutionStart(
            task_description=task_description,
            message="🚀 Starting enhanced plan-and-execute task..."
        )
        
        try:
            # 1. 创建执行计划
            yield PlanGenerationStart(message="🧠 Analyzing task and creating execution plan...")
            plan = yield from self.planner.create_execution_plan(task_description)
            
            yield PlanGenerationEnd(
                plan=plan,
                message=f"📋 Created execution plan with {len(plan.steps)} steps"
            )
            
            # 2. 执行计划
            final_result: Optional[ExecutionResult] = None
            execution_start_time = time.time()
            
            while plan.can_continue():
                next_step = plan.get_next_executable_step()
                if not next_step:
                    break
                
                self.execution_stats["total_steps"] += 1
                
                # 执行步骤
                step_result, exec_res_obj = yield from self._execute_step(plan, next_step)
                
                if step_result["success"]:
                    plan.mark_step_completed(
                        next_step.step_id, 
                        True, 
                        step_result["result"]
                    )
                    
                    # 更新执行上下文
                    plan.context[f"step_{next_step.step_id}_result"] = step_result["result"]
                    
                    # 如果是最后一步，保存最终结果
                    if next_step == plan.steps[-1] and isinstance(exec_res_obj, ExecutionResult):
                        final_result = exec_res_obj
                
                else:
                    # 步骤失败处理
                    self.execution_stats["failed_steps"] += 1
                    error_msg = step_result.get("error", "Unknown error")
                    plan.mark_step_completed(next_step.step_id, False, error=error_msg)
                    
                    # 尝试恢复
                    if next_step.retry_count < next_step.max_retries:
                        yield from self._handle_step_failure(plan, next_step)
                    else:
                        yield ExecutorError(
                            step=next_step,
                            message=f"❌ Step {next_step.step_id} failed after {next_step.max_retries} retries.",
                            error_details=error_msg
                        )
                        break
            
            # 3. 任务完成
            execution_time = time.time() - execution_start_time
            
            if final_result and final_result.success:
                self.execution_stats["successful_tasks"] += 1
                yield TaskExecutionEnd(
                    success=True,
                    final_result=final_result,
                    execution_time=execution_time,
                    stats=self.execution_stats.copy(),
                    message=f"✅ Task completed successfully in {execution_time:.2f}s"
                )

                final_script = None
                for step in plan.steps:
                    if step.action == 'run_dolphindb_script' and step.status == StepStatus.SUCCESS:
                        final_script = step.args.get('script')

                if final_script:
                    yield FinalScriptExtracted(
                        script=final_script,
                        message="Extracted the final successful script from the plan."
                    )
            else:
                self.execution_stats["failed_tasks"] += 1
                error_details = final_result.error_message if final_result else "Plan did not complete successfully."
                yield TaskExecutionEnd(
                    success=False,
                    final_result=final_result,
                    execution_time=execution_time,
                    stats=self.execution_stats.copy(),
                    message=f"❌ Task failed after {execution_time:.2f}s: {error_details}"
                )
        
        except Exception as e:
            self.execution_stats["failed_tasks"] += 1
            import traceback
            tb_str = traceback.format_exc()
            self.logger.error(f"Unexpected error during task execution: {tb_str}")
            yield ExecutorError(
                message=f"💥 Unexpected error during task execution: {str(e)}",
                error_details=tb_str
            )
    
    def _execute_step(self, plan: ExecutionPlan, step: PlanStep) -> Generator[AnyExecutorStatus, None, Tuple[Dict, Optional[ExecutionResult]]]:
        """执行单个步骤"""
        step.status = StepStatus.RUNNING
        
        yield StepExecutionStart(
            step=step,
            message=f"▶️ Executing step {step.step_id}: {step.action}"
        )
        
        exec_res_obj: Optional[ExecutionResult] = None
        try:
            # 调用工具
            start_time = time.time()
            tool_result =  self.tool_manager.call_tool(step.action, step.args)
            execution_time = time.time() - start_time
            
            # 分析结果
            if isinstance(tool_result, ExecutionResult):
                exec_res_obj = tool_result
                success = tool_result.success
                observation = str(tool_result.data) if success else tool_result.error_message
            else:
                success = True # 假设非ExecutionResult都是成功的
                observation = str(tool_result)
                exec_res_obj = ExecutionResult(success=True, data=observation)

            yield StepExecutionEnd(
                step=step,
                result=exec_res_obj,
                execution_time=execution_time,
                message=f"{'✅' if success else '❌'} Step {step.step_id} {'completed' if success else 'failed'}"
            )
            
            return {
                "success": success,
                "result": tool_result,
                "error": None if success else observation
            }, exec_res_obj
        
        except Exception as e:
            error_msg = f"Tool execution error: {str(e)}"
            exec_res_obj = ExecutionResult(success=False, error_message=error_msg)

            yield StepExecutionEnd(
                step=step,
                result=exec_res_obj,
                execution_time=0.0,
                message=f"❌ Step {step.step_id} failed with exception"
            )
            
            return { "success": False, "result": None, "error": error_msg }, exec_res_obj
    
    def _handle_step_failure(self, plan: ExecutionPlan, failed_step: PlanStep) -> Generator[AnyExecutorStatus, None, None]:
        """处理步骤失败"""
        self.execution_stats["recovery_attempts"] += 1
        
        yield RecoveryPlanStart(
            failed_step=failed_step,
            message=f"🔧 Step {failed_step.step_id} failed, attempting recovery..."
        )
        
        try:
            # 生成恢复计划
            recovery_plan = yield from self.planner.handle_step_failure(plan, failed_step)
            
            yield RecoveryPlanEnd(
                new_plan=recovery_plan,
                message=f"🔄 Generated recovery plan with {len(recovery_plan.steps) - len([s for s in recovery_plan.steps if s.status == StepStatus.SUCCESS])} new steps"
            )
            
            # 更新计划
            plan.steps = recovery_plan.steps
            plan.current_step = recovery_plan.current_step
            
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self.logger.error(f"Recovery planning failed: {tb_str}")
            yield ExecutorError(
                message=f"🚨 Recovery planning failed: {str(e)}",
                step=failed_step,
                error_details=tb_str
            )
    
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