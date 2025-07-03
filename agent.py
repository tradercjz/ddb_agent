# file: ddb_agent/agent.py (之前在main.py中虚构的，现在正式实现)

from typing import List, Dict, Any
from session.session_manager import SessionManager
from context.context_builder import ContextBuilder
from rag.rag_entry import DDBRAG
from llm.llm_prompt import llm # 假设llm实例在这里

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

    def run_task(self, user_input: str, task_type: str = 'chat'):
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
        assistant_response = self.chat_prompt_func(
            conversation_history=final_messages
        )

        # 6. 更新会话并保存
        self.session_manager.add_message('assistant', assistant_response)
        self.session_manager.save_session()

        return assistant_response