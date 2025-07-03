from typing import Dict, Literal

# CONTEXT_WEIGHTS 现在只定义 history 和 file_context 的相对权重
CONTEXT_WEIGHTS = {
    "default": {
        "conversation_history": 0.40,
        "file_context": 0.60,
    },
    "coding": {
        "conversation_history": 0.25,
        "file_context": 0.75, # 编码时，文件上下文权重更高
    },
    "chat": {
        "conversation_history": 0.70, # 聊天时，对话历史权重更高
        "file_context": 0.30,
    }
}

class ContextBudget:
    """
    Calculates the token budget for conversation history and file context,
    after reserving space for a fixed system prompt.
    """
    def __init__(
        self, 
        total_safe_zone: int, 
        system_prompt_tokens: int,
        task_type: Literal['default', 'coding', 'chat'] = 'default'
    ):
        if task_type not in CONTEXT_WEIGHTS:
            raise ValueError(f"Unknown task type: {task_type}")

        # 1. 首先为 system_prompt 预留空间
        self.system_prompt_tokens = system_prompt_tokens
        
        if self.system_prompt_tokens >= total_safe_zone:
            raise ValueError(
                f"System prompt alone ({self.system_prompt_tokens} tokens) "
                f"exceeds or equals the total safe zone ({total_safe_zone} tokens)."
            )

        # 2. 计算剩余的可用预算
        remaining_budget = total_safe_zone - self.system_prompt_tokens
        
        # 3. 根据权重分配剩余预算
        self.weights = CONTEXT_WEIGHTS[task_type]
        self.history_budget = int(remaining_budget * self.weights["conversation_history"])
        self.file_context_budget = int(remaining_budget * self.weights["file_context"])

        # 4. 调整以确保总和精确
        self._adjust_budgets(remaining_budget)
        
    def _adjust_budgets(self, remaining_budget: int):
        """Adjusts budgets to ensure they sum up to the remaining budget."""
        current_sum = self.history_budget + self.file_context_budget
        diff = remaining_budget - current_sum
        # 将误差加到权重最大的部分上
        if self.weights["file_context"] > self.weights["conversation_history"]:
            self.file_context_budget += diff
        else:
            self.history_budget += diff