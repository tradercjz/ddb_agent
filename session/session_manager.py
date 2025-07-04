# file: ddb_agent/session/session_manager.py

import os
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

class SessionManager:
    """
    Manages loading, saving, and accessing the persistent conversation history for a session.
    """
    def __init__(self, project_path: str, session_file: str = ".ddb_agent/session.json"):
        self.session_path = os.path.join(project_path, session_file)
        self.session_data: Dict[str, Any] = self._load_or_create_session()

    def _load_or_create_session(self) -> Dict[str, Any]:
        """
        Loads an existing session from disk, or creates a new one if it doesn't exist.
        """
        os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
        if os.path.exists(self.session_path):
            print(f"Loading existing session from: {self.session_path}")
            try:
                with open(self.session_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load session file. A new session will be created. Error: {e}")
        
        # 创建一个新的会话
        print("No existing session found. Creating a new session.")
        return self._create_new_session_data()

    def _create_new_session_data(self) -> Dict[str, Any]:
        """Creates the data structure for a new session."""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "session_id": f"sid_{uuid.uuid4().hex}",
            "created_at": now,
            "updated_at": now,
            "conversation_history": [],
            "metadata": {}
        }

    def save_session(self):
        """
        Saves the current session data to the disk.
        """
        self.session_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.session_path, 'w', encoding='utf-8') as f:
                json.dump(self.session_data, f, indent=2)
            print(f"Session saved to: {self.session_path}")
        except IOError as e:
            print(f"Error: Could not save session file. {e}")

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Returns the current conversation history.
        """
        return self.session_data.get("conversation_history", [])

    def add_message(self, role: str, content: str):
        """
        Adds a new message to the conversation history.

        Args:
            role: The role of the speaker ('user' or 'assistant').
            content: The content of the message.
        """
        if role not in ['user', 'assistant', 'system']:
            raise ValueError("Role must be 'user', 'assistant', or 'system'.")
        
        self.session_data["conversation_history"].append({
            "role": role,
            "content": content
        })

    def new_session(self):
        """
        Archives the current session (if it has history) and starts a new one.
        """
        if self.get_history():
             # (可选) 归档旧会话，而不是直接覆盖
            archive_dir = os.path.join(os.path.dirname(self.session_path), "history")
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, f"session_{self.session_data['session_id']}.json")
            try:
                os.rename(self.session_path, archive_path)
                print(f"Archived previous session to: {archive_path}")
            except OSError as e:
                print(f"Could not archive previous session: {e}")
        
        # 创建新会话
        self.session_data = self._create_new_session_data()
        self.save_session()
        print("Started a new session.")