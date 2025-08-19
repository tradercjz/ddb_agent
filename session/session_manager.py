# file: ddb_agent/session/session_manager.py

import os
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from session.summarizer import HistorySummarizer
from token_counter import count_tokens

class SessionManager:
    """
    (无状态改造) 管理会话数据的加载和保存。
    这个类本身不持有任何激活的会话状态，是线程安全的。
    """
    def __init__(self, project_path: str, session_dir: str = ".ddb_agent/sessions"):
        self.base_path = os.path.join(project_path, session_dir)
        os.makedirs(self.base_path, exist_ok=True)

    def _get_session_path(self, session_id: str) -> str:
        """根据 session_id 获取文件路径。"""
        return os.path.join(self.base_path, f"{session_id}.json")

    def _create_new_session_data(self, session_id: str) -> Dict[str, Any]:
        """创建一个新的会话数据结构。"""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "session_id": session_id,
            "session_name": session_id, # name 和 id 可以相同，或由上层管理
            "created_at": now,
            "updated_at": now,
            "summary": "",
            "conversation_history": [],
            "metadata": {}
        }

    def load_session_data(self, session_id: str) -> Dict[str, Any]:
        """
        根据 session_id 加载并返回会话数据。
        如果文件不存在或加载失败，则返回一个新的空会话结构。
        """
        session_path = self._get_session_path(session_id)
        if os.path.exists(session_path):
            try:
                with open(session_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load session file for '{session_id}'. Creating new. Error: {e}")
        
        return self._create_new_session_data(session_id)

    def save_session_data(self, session_id: str, session_data: Dict[str, Any]):
        """将会话数据保存到对应的 session_id 文件中。"""
        session_path = self._get_session_path(session_id)
        session_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        try:
            with open(session_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Error: Could not save session file for '{session_id}'. {e}")

    def list_sessions(self) -> List[Dict[str, str]]:
        """返回所有可用会话的ID和名称列表。"""
        sessions = []
        try:
            for f in os.scandir(self.base_path):
                if f.is_file() and f.name.endswith('.json'):
                    session_id = os.path.splitext(f.name)[0]
                    # 为了简单，我们假设 session_name 和 session_id 相同
                    sessions.append({"id": session_id, "name": session_id})
            return sessions
        except FileNotFoundError:
            return []

    # --- 长期记忆逻辑 (静态方法，因为它们是无状态的) ---
    @staticmethod
    def get_contextual_history(session_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        根据会话数据，构建包含长期记忆（摘要）的上下文历史。
        这是一个无状态的辅助函数。
        """
        final_context = []
        summary = session_data.get("summary")
        if summary:
            final_context.append({
                "role": "system",
                "content": f"This is a summary of the conversation so far. Use it for long-term context:\n\n---\n{summary}\n---"
            })
        
        final_context.extend(session_data.get("conversation_history", []))
        return final_context

    @staticmethod
    def summarize_if_needed(session_data: Dict[str, Any], max_tokens=30000, retain_count=10) -> bool:
        """
        检查是否需要总结，如果需要则执行并更新 session_data。
        返回 True 表示执行了总结，否则返回 False。
        """
        history = session_data.get("conversation_history", [])
        current_tokens = sum(count_tokens(str(msg.get('content', ''))) for msg in history)
        
        if current_tokens > max_tokens and len(history) > retain_count:
            messages_to_summarize = history[:-retain_count]
            messages_to_retain = history[-retain_count:]
            
            existing_summary = session_data.get("summary", "")
            full_content_to_summarize = [
                {"role": "system", "content": f"Previous summary:\n{existing_summary}"}
            ] + messages_to_summarize

            new_summary = HistorySummarizer.summarize(full_content_to_summarize)
            
            # 直接修改传入的字典
            session_data["summary"] = new_summary
            session_data["conversation_history"] = messages_to_retain
            return True
        return False