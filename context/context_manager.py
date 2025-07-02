# file: ddb_agent/context/context_manager.py (处理超长单条消息)

from typing import List, Dict, Any
from token_counter import count_tokens

class ContextManager:
    """
    Manages the context window for LLM calls by dynamically pruning content,
    including handling single oversized messages.
    """
    def __init__(self, model_name: str, max_window_size: int = 50000):
        self.model_name = model_name
        self.max_window_size = max_window_size
        self.safe_zone_size = int(max_window_size * 0.9)

    def _truncate_single_message(self, message: Dict[str, str]) -> Dict[str, str]:
        """
        Truncates a single message if it exceeds the safe zone size.
        A warning is added to the content indicating it has been truncated.
        """
        content = message.get('content', '')
        message_tokens = count_tokens(content, model_name=self.model_name)

        if message_tokens > self.safe_zone_size:
            print(f"Warning: A single message (role: {message['role']}) with {message_tokens} tokens "
                  f"exceeds the safe zone of {self.safe_zone_size}. It will be truncated.")
            
            # --- 截断策略 ---
            # 更智能的策略可能是保留开头和结尾，但这里先实现一个简单的从头截断
            # 我们需要估算能保留多少文本
            avg_chars_per_token = len(content) / message_tokens if message_tokens > 0 else 4
            safe_char_count = int(self.safe_zone_size * avg_chars_per_token * 0.95) # 再留5%余量

            truncated_content = content[:safe_char_count]
            
            # 在被截断的内容末尾添加一个警告
            truncation_warning = "\n\n[---SYSTEM WARNING: This content has been truncated due to context window limitations.---]"
            
            # 创建一个新的消息字典，而不是修改原始的
            return {
                'role': message['role'],
                'content': truncated_content + truncation_warning
            }
        
        return message # 如果消息不大，原样返回

    def prune(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Prunes the list of messages to fit within the safe zone of the context window.
        This now includes a pre-processing step to handle oversized single messages.
        """
        if not messages:
            return []

        # --- 第1步：单消息预处理层 ---
        # 遍历所有消息，对可能超长的消息进行截断
        pre_processed_messages = [self._truncate_single_message(msg) for msg in messages]

        # --- 第2步：多消息整体剪枝层 (逻辑与之前类似) ---
        total_tokens = self._count_total_tokens(pre_processed_messages)

        if total_tokens <= self.safe_zone_size:
            print(f"Total tokens within safe zone: {total_tokens}. No pruning needed.")
            return pre_processed_messages

        print(f"Context window overflow detected. Total tokens: {total_tokens}, "
              f"Safe zone: {self.safe_zone_size}. Pruning conversation history...")

        # 剪枝策略：保留系统提示，移除旧的对话
        system_prompt = None
        if pre_processed_messages[0]['role'] == 'system':
            system_prompt = pre_processed_messages[0]
            workable_messages = pre_processed_messages[1:]
        else:
            workable_messages = pre_processed_messages

        while self._count_total_tokens([system_prompt] + workable_messages if system_prompt else workable_messages) > self.safe_zone_size:
            if not workable_messages:
                # 经过单条消息截断后，这里几乎不可能再出现系统提示单独超长的情况
                # 但保留这个检查以防万一
                raise ValueError("System prompt alone exceeds the context window safe zone even after potential truncation.")
            
            removed_message = workable_messages.pop(0)
            print(f"  - Pruned historical message (role: {removed_message['role']}): '{removed_message['content'][:50]}...'")

        final_messages = [system_prompt] + workable_messages if system_prompt else workable_messages
        
        final_tokens = self._count_total_tokens(final_messages)
        print(f"Pruning complete. Final token count: {final_tokens}")

        return final_messages

    def _count_total_tokens(self, messages: List[Dict[str, str]]) -> int:
        if not messages:
            return 0
        full_text = "".join(msg.get('content', '') for msg in messages if msg) # 增加 if msg 保护
        return count_tokens(full_text, model_name=self.model_name)