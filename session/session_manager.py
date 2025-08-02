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
    Manages loading, saving, and accessing persistent conversation history
    for multiple, named sessions, including summarization for long-term memory.
    """
    def __init__(self, project_path: str, session_dir: str = ".ddb_agent/sessions"):
        self.base_path = os.path.join(project_path, session_dir)
        self.config_file = os.path.join(project_path, ".ddb_agent", "session_config.json")
        os.makedirs(self.base_path, exist_ok=True)

        self.active_session_name: str = self._load_active_session_name()
        self.session_data: Dict[str, Any] = self._load_session(self.active_session_name)
        
        # Configuration for summarization
        self.max_history_tokens = 30000  # Soft limit to trigger summarization
        self.retained_messages_count = 10 # Keep the last N messages out of the summary

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
    
    def _get_session_path(self, session_name: str) -> str:
        """Gets the full path for a given session name."""
        return os.path.join(self.base_path, f"{session_name}.json")
    
    def _load_active_session_name(self) -> str:
        """Loads the name of the last active session, or defaults to 'default'."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f).get("active_session", "default")
            except (json.JSONDecodeError, IOError):
                pass
        return "default"

    def _save_active_session_name(self):
        """Saves the current active session name to the config file."""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump({"active_session": self.active_session_name}, f)

    def _load_session(self, session_name: str) -> Dict[str, Any]:
        """Loads a specific session from disk, or creates it if it doesn't exist."""
        session_path = self._get_session_path(session_name)
        if os.path.exists(session_path):
            print(f"Loading session '{session_name}' from: {session_path}")
            try:
                with open(session_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load session file '{session_name}'. A new session will be created. Error: {e}")
        
        # Create a new session if not found
        return self._create_new_session_data(session_name)

    def _create_new_session_data(self, session_name: str) -> Dict[str, Any]:
        """Creates the data structure for a new session."""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "session_id": f"sid_{uuid.uuid4().hex}",
            "session_name": session_name,
            "created_at": now,
            "updated_at": now,
            "summary": "", # New field for long-term memory
            "conversation_history": [],
            "metadata": {}
        }

    def save_session(self):
        """Saves the current active session data to disk."""
        session_path = self._get_session_path(self.active_session_name)
        self.session_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        try:
            with open(session_path, 'w', encoding='utf-8') as f:
                json.dump(self.session_data, f, indent=2, ensure_ascii=False)
            print(f"Session '{self.active_session_name}' saved to: {session_path}")
        except IOError as e:
            print(f"Error: Could not save session file '{self.active_session_name}'. {e}")

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Returns the contextual conversation history.
        If the history is too long, it will be summarized and compacted.
        """
        history = self.session_data.get("conversation_history", [])
        
        # --- Summarization Logic ---
        current_tokens = sum(count_tokens(msg.get('content', '')) for msg in history)
        
        if current_tokens > self.max_history_tokens and len(history) > self.retained_messages_count:
            print("INFO: History exceeds token limit, triggering summarization.")
            
            # Split history into what to summarize and what to keep
            messages_to_summarize = history[:-self.retained_messages_count]
            messages_to_retain = history[-self.retained_messages_count:]
            
            # Combine new summary with previous summary
            existing_summary = self.session_data.get("summary", "")
            full_content_to_summarize = [
                {"role": "system", "content": f"Previous summary:\n{existing_summary}"}
            ] + messages_to_summarize

            # Generate new summary
            new_summary = HistorySummarizer.summarize(full_content_to_summarize)
            
            # Update session data
            self.session_data["summary"] = new_summary
            self.session_data["conversation_history"] = messages_to_retain
            
            # Save the compacted session immediately
            self.save_session()
            print("INFO: History summarization complete and session saved.")

        # --- Construct final context for the LLM ---
        final_context = []
        summary = self.session_data.get("summary")
        if summary:
            final_context.append({
                "role": "system",
                "content": f"This is a summary of the conversation so far. Use it for long-term context:\n\n---\n{summary}\n---"
            })
        
        final_context.extend(self.session_data.get("conversation_history", []))
        return final_context

    def add_message(self, role: str, content: str):
        """Adds a new message to the conversation history of the active session."""
        if role not in ['user', 'assistant', 'system']:
            raise ValueError("Role must be 'user', 'assistant', or 'system'.")
        
        self.session_data.setdefault("conversation_history", []).append({
            "role": role,
            "content": content
        })

    def switch_session(self, new_session_name: str):
        """Switches the active session to a new or existing one."""
        if not new_session_name.strip():
            raise ValueError("Session name cannot be empty.")
        
        # Save current session before switching
        self.save_session()
        
        self.active_session_name = new_session_name
        self.session_data = self._load_session(new_session_name)
        self._save_active_session_name()
        print(f"Switched to session: '{new_session_name}'")

    def new_session(self, session_name: Optional[str] = None):
        """Creates and switches to a new session."""
        new_name = session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.switch_session(new_name)
        
    def list_sessions(self) -> List[str]:
        """Returns a list of all available session names."""
        try:
            return [os.path.splitext(f.name)[0] for f in os.scandir(self.base_path) if f.is_file() and f.name.endswith('.json')]
        except FileNotFoundError:
            return []

    def get_active_session_name(self) -> str:
        return self.active_session_name