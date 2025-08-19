import os
import json
from typing import Generator, Union, List, Dict, Any

from agent.agent import DDBAgent, FinalMessage
from llm.llm_client import StreamChunk
from mcp.market.market_manager import MCPMarketManager
from mcp.server.server_manager import MCPServerManager
from session.session_manager import SessionManager
from agent.task_status import AnyTaskStatus
from rag.rag_status import AnyRagStatus
from datetime import datetime

class CLISessionHandler:
    """
    为CLI环境提供有状态的会话管理。
    它包装了无状态的DDBAgent核心。
    """
    def __init__(self, project_path: str, model_name: str, max_window_size: int, mcp_market_manager: MCPMarketManager, mcp_server_manager: MCPServerManager):
        # 1. 初始化无状态的Agent核心和SessionManager工具集
        self.agent_core = DDBAgent(
            project_path=project_path,
            model_name=model_name,
            max_window_size=max_window_size,
            mcp_market_manager = mcp_market_manager,
            mcp_server_manager = mcp_server_manager
        )
        self.session_manager = SessionManager(project_path=project_path)
        
        # 2. 管理CLI的当前会话状态
        self.config_file = os.path.join(project_path, ".ddb_agent", "session_config.json")
        self.active_session_id = self._load_active_session_id()

    def _load_active_session_id(self) -> str:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f).get("active_session", "default")
            except (json.JSONDecodeError, IOError):
                pass
        return "default"

    def _save_active_session_id(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump({"active_session": self.active_session_id}, f)

    # --- CLI会话管理命令 ---
    def new_session(self, session_id: str = None):
        if session_id is None:
            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.active_session_id = session_id
        self._save_active_session_id()
        self.session_manager.save_session_data(session_id, self.session_manager._create_new_session_data(session_id))
        
    def switch_session(self, session_id: str):
        self.active_session_id = session_id
        self._save_active_session_id()

    def get_active_session_name(self) -> str:
        return self.active_session_id

    def list_sessions(self) -> List[Dict[str, str]]:
        return self.session_manager.list_sessions()

    # --- CLI任务执行入口 ---
    def run_react_task(self, user_input: str) -> Generator[Union[AnyRagStatus, AnyTaskStatus], None, None]:
        # 1. 加载当前会话数据
        session_data = self.session_manager.load_session_data(self.active_session_id)
        
        # 2. 更新历史记录 (长期记忆总结)
        if self.session_manager.summarize_if_needed(session_data):
            print("INFO: History summarized and compacted.")

        # 3. 获取上下文历史并添加新消息
        contextual_history = self.session_manager.get_contextual_history(session_data)
        contextual_history.append({"role": "user", "content": user_input})
        
        # 4. 调用无状态核心执行任务
        task_generator = self.agent_core.run_react_task(contextual_history)
        
        # 5. 处理结果并更新会话
        final_message_obj = None
        for update in task_generator:
            if isinstance(update, FinalMessage):
                final_message_obj = update.message_object
            else:
                yield update # 将其他状态直接传递给TUI
        
        # 6. 保存更新后的会话
        if final_message_obj:
            session_data["conversation_history"].append({"role": "user", "content": user_input})
            session_data["conversation_history"].append(final_message_obj)
            self.session_manager.save_session_data(self.active_session_id, session_data)

    def run_chat_task(self, user_input: str) -> Generator[Union[AnyRagStatus, StreamChunk], None, None]:
        """
        (CLI包装器) 处理一个有状态的聊天任务。
        负责加载、更新和保存会话。
        """
        # 1. 加载和处理当前会话
        session_data = self.session_manager.load_session_data(self.active_session_id)
        if SessionManager.summarize_if_needed(session_data):
            self.notify("History summarized and compacted.", title="Session Notice")
            
        contextual_history = SessionManager.get_contextual_history(session_data)
        contextual_history.append({"role": "user", "content": user_input})
        
        # 2. 调用无状态的 agent_core
        task_generator = self.agent_core.run_chat_task(contextual_history)
        
        final_message_obj = None
        # 3. 消费生成器，将状态更新传递给TUI，并捕获最终消息
        for update in task_generator:
            if isinstance(update, FinalMessage):
                final_message_obj = update.message_object
            else:
                yield update # 将 AnyRagStatus 和 StreamChunk 传递给 TUI

        # 4. 保存更新后的会话
        if final_message_obj:
            # 将用户输入和助手回复都添加到历史记录中
            session_data["conversation_history"].append({"role": "user", "content": user_input})
            session_data["conversation_history"].append(final_message_obj)
            self.session_manager.save_session_data(self.active_session_id, session_data)


    def run_interactive_sql_task(self, user_input: str) -> Generator[Union[AnyRagStatus, AnyTaskStatus], None, None]:
        # 1. 加载当前会话数据
        session_data = self.session_manager.load_session_data(self.active_session_id)
        
        # 2. 检查是否需要摘要
        if self.session_manager.summarize_if_needed(session_data):
            print("INFO: History summarized and compacted.")

        # 3. 获取上下文历史
        contextual_history = self.session_manager.get_contextual_history(session_data)
        
        # 4. 调用无状态核心执行任务
        # 注意：这里 user_input 也被传入，因为 executor 的逻辑需要它
        final_history = yield from self.agent_core.run_interactive_sql_task(user_input, contextual_history)
        
       

        # 6. 保存更新后的会话
        if final_history:
            # 用 executor 返回的完整交互历史替换旧的 conversation_history
            # 因为它已经包含了初始的用户输入和所有中间步骤
            session_data["conversation_history"] = final_history
            self.session_manager.save_session_data(self.active_session_id, session_data)
        else:
            # 如果没有返回历史（可能出错了），至少保存用户的输入
            session_data["conversation_history"].append({"role": "user", "content": user_input})
            session_data["conversation_history"].append({"role": "assistant", "content": "[Task ended unexpectedly without returning history]"})
            self.session_manager.save_session_data(self.active_session_id, session_data)