# file: ddb_agent/context/context_builder.py (重构后)

from typing import List, Dict, Any, Literal

from .pruner import get_pruner, Document
from .budget import ContextBudget
from token_counter import count_tokens

class ContextBuilder:
    """
    Orchestrates building the LLM context with dynamic budget allocation
    and a reserved space for the system prompt.
    """
    def __init__(self, model_name: str, max_window_size: int):
        self.model_name = model_name
        self.max_window_size = max_window_size
        self.safe_zone = int(max_window_size * 0.9)

    def build(
        self,
        system_prompt: str,
        conversations: List[Dict[str, Any]],
        file_sources: List[Document],
        task_type: Literal['default', 'coding', 'chat'] = 'default',
        file_pruning_strategy: str = 'extract'
    ) -> List[Dict[str, Any]]:
        
        # 1. 首先计算不可动摇的 system_prompt 的 token 数
        system_prompt_tokens = count_tokens(system_prompt, self.model_name)

        # 2. 基于 system_prompt 的开销，创建预算分配器
        try:
            budget = ContextBudget(
                total_safe_zone=self.safe_zone,
                system_prompt_tokens=system_prompt_tokens,
                task_type=task_type
            )
        except ValueError as e:
            # 如果 system_prompt 本身就超限了，这是一个严重错误
            print(f"Error: {e}")
            # 我们可以选择返回一个只包含截断后的系统提示的最小化上下文
            return [{"role": "system", "content": self._prune_system_prompt(system_prompt, self.safe_zone)}]

        # 3. 剪枝对话历史 (使用分配好的预算)
        pruned_conversations = self._prune_conversation_history(conversations, budget.history_budget)
        
        # 4. 剪枝文件上下文 (使用分配好的预算)
        file_pruner = get_pruner(
            strategy=file_pruning_strategy, 
            max_tokens=budget.file_context_budget,
            llm_model_name=self.model_name
        )
        pruned_file_sources = file_pruner.prune(file_sources, conversations)

        # 5. 组合最终上下文
        final_messages = [{"role": "system", "content": system_prompt}]
        
        if pruned_file_sources:
            file_context_str = "\n---\n".join(
                f"File: {f.file_path}\n\n{f.source_code}" for f in pruned_file_sources
            )
            final_messages.append({"role": "assistant", "content": f"<CONTEXT_FILES>\n{file_context_str}\n</CONTEXT_FILES>"})
           
        final_messages.extend(pruned_conversations)

        return final_messages

    def _prune_system_prompt(self, prompt: str, budget: int) -> str:
        # 这个方法现在主要用于极端情况下的报错和截断
        if count_tokens(prompt, self.model_name) > budget:
            print(f"CRITICAL WARNING: System prompt is too long ({count_tokens(prompt, self.model_name)} tokens) "
                  f"and exceeds the total budget ({budget} tokens). It will be severely truncated.")
            avg_chars_per_token = len(prompt) / count_tokens(prompt, self.model_name) if count_tokens(prompt, self.model_name) > 0 else 4
            safe_chars = int(budget * avg_chars_per_token * 0.95)
            return prompt[:safe_chars]
        return prompt

    def _prune_conversation_history(self, conversations: List[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
        """Prunes conversation history using a sliding window approach."""
        pruned_history = []
        current_tokens = 0
        
        # 从最新（末尾）的对话开始保留
        for msg in reversed(conversations):
            msg_tokens = count_tokens(msg.get('content', ''), self.model_name)
            if current_tokens + msg_tokens <= budget:
                pruned_history.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break
        
        return pruned_history