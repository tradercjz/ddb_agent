import os
import json
import time
from typing import Generator, Tuple, Union, List, Dict, Any, Optional

import httpx
from openai import APIError

from agent.agent import DDBAgent, FinalMessage
from agent.cloud_client import AuthError, CloudClient
from agent.interactive_sql_executor import InteractiveSQLExecutor
from llm.llm_client import StreamChunk
from mcp.market.market_manager import MCPMarketManager
from mcp.server.server_manager import MCPServerManager
from session.session_manager import SessionManager
from agent.task_status import AnyTaskStatus
from rag.rag_status import AnyRagStatus
from datetime import datetime
import pandas as pd
from agent.file_handler import FileHandler
from datetime import datetime
from agent.cloud_schemas import CloudTaskUpdate
import re
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
        self.file_handler = FileHandler()
        self.cloud_client = CloudClient(base_url="https://www.kineticalpha.cn")

    def cloud_login(self, username: str, password: str) -> Tuple[bool, str]:
        """
        Handles the logic for logging into the cloud service.
        This method is synchronous and data-only.
        
        Returns:
            A tuple containing (success_boolean, message_string).
        """
        try:
            self.cloud_client.login(username, password)
            return True, "✅ Login successful. You can now manage cloud environments."
        except (AuthError, APIError, httpx.RequestError) as e:
            return False, f"❌ Login failed: {e}"
        
    def cloud_list_vms(self) -> List[Dict[str, Any]]:
        """
        Fetches environments and returns them as a list of dictionaries.
        NO UI FORMATTING.
        """
        try:
            return self.cloud_client.list_environments()
        except (AuthError, APIError, httpx.RequestError) as e:
            raise e

    def cloud_create_vm(self, spec: str) -> Generator[CloudTaskUpdate, None, None]:
        """
        A synchronous generator that yields structured CloudTaskUpdate objects.
        NO UI WIDGETS.
        """
        try:
            match = re.match(r'(\d+)c(\d+)g', spec.lower())
            if not match:
                yield CloudTaskUpdate(status="ERROR", message=f"Invalid spec format: '{spec}'. Use format like '2c4g'.")
                return
            cpu, mem = float(match.group(1)), float(match.group(2))

            yield CloudTaskUpdate(status="IN_PROGRESS", message=f"Sending request to create a {cpu}c/{mem}G environment...")
            
            env = self.cloud_client.create_environment(cpu, mem, 24)
            env_id = env['id']

            timeout = 600
            start_time = time.time()
            last_message = ""
            while time.time() - start_time < timeout:
                status_env = self.cloud_client.get_environment_status(env_id)
                status = status_env['status']
                message = status_env.get('message', 'Waiting...')

                if message != last_message:
                    yield CloudTaskUpdate(status="IN_PROGRESS", message=f"[{status}] {message}")
                    last_message = message

                if status == 'RUNNING':
                    yield CloudTaskUpdate(status="SUCCESS", message=f"Your environment '{env_id}' is ready.")
                    # Yield the final list as a special update type
                    final_list = self.cloud_list_vms()
                    yield CloudTaskUpdate(status="FINAL_LIST", message="Final environment list.", details={"environments": final_list})
                    return
                elif status == 'ERROR':
                    yield CloudTaskUpdate(status="ERROR", message=f"Creation failed. Reason: {message}")
                    return
                
                time.sleep(5)
            
            yield CloudTaskUpdate(status="ERROR", message=f"Timed out after {timeout} seconds.")

        except (AuthError, APIError, httpx.RequestError) as e:
            yield CloudTaskUpdate(status="ERROR", message=f"An API error occurred: {str(e)}")

    def cloud_delete_vm(self, env_id: str) -> Tuple[bool, str]:
        """
        Calls the cloud client to schedule a VM for deletion.
        Returns a tuple of (success, message).
        """
        try:
            response = self.cloud_client.delete_environment(env_id)
            message = response.get("message", f"Deletion scheduled for '{env_id}'.")
            return True, f"✅ {message}"
        except (AuthError, APIError, httpx.RequestError) as e:
            return False, f"❌ Error deleting environment: {e}"
        
    def switch_connection(self, connection_name: str) -> Tuple[bool, str]:
        """
        Switches the agent's active DolphinDB connection.
        This is the core logic that tells the agent to reconfigure its CodeExecutor.
        """
        try:
            # Case 1: Switching back to the default local connection
            if connection_name.lower() in ["local", "default"]:
                # Pass an empty dict to signal CodeExecutor to load from .env
                self.agent_core.reconfigure_executor({}) 
                return True, "✅ Switched to default **local** connection."

            # Case 2: Switching to a cloud environment
            if not self.cloud_client.is_logged_in:
                 return False, "❌ You must be logged in to connect to a cloud environment."

            envs = self.cloud_client.list_environments()
            target_env = next(
                (e for e in envs if e['id'] == connection_name and e['status'] == 'RUNNING'), 
                None
            )

            if not target_env:
                return False, f"❌ A running cloud environment named '{connection_name}' was not found."

            connection_details = {
                "host": target_env['public_ip'],
                "port": target_env['port'],
                "user": "admin", # Assuming default credentials for now
                "password": "123456" 
            }
            self.agent_core.reconfigure_executor(connection_details)
            return True, f"✅ Switched connection to cloud environment: **{connection_name}**"

        except (AuthError, APIError, httpx.RequestError) as e:
            return False, f"❌ Error switching connection: {e}"

    def get_connection_status(self) -> Dict[str, Any]:
        """
        Retrieves the current connection details from the agent's core.
        Returns a data dictionary, not a UI element.
        """
        return self.agent_core.get_connection_details()

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
    
    # --- 使用'@'文件注入上下文相关的核心逻辑 ---
    def preprocess_and_inject_files(self, file_paths: List[str]) -> Tuple[bool, str]:
        """
        批量处理文件引用，更新会话的 injected_context，并一次性保存。
        """
        # 确保列表是唯一的，避免重复处理
        unique_file_paths = sorted(list(set(file_paths)))

        session_data = self.session_manager.load_session_data(self.active_session_id)
        
        # 确保 injected_context 结构存在
        session_data.setdefault('injected_context', {})
        session_data['injected_context'].setdefault('files', {})

        newly_processed_count = 0
        errors = []
        messages = []

        for file_path in unique_file_paths:
            # 如果文件已在上下文中，则跳过
            if file_path in session_data['injected_context']['files']:
                continue

            success, message, context_obj = self.file_handler.process_file(file_path)
            messages.append(f"- {file_path}: {message}")

            if success:
                if context_obj: # 仅当 context_obj 非空时才注入
                    session_data['injected_context']['files'][file_path] = context_obj
                    newly_processed_count += 1
            else:
                errors.append(message)

        if errors:
            return False, "Some files could not be processed:\n" + "\n".join(errors)

        # 只有在实际添加了新文件时才保存
        if newly_processed_count > 0:
            self.session_manager.save_session_data(self.active_session_id, session_data)

        return True, "\n".join(messages)
    
    # --- 数据库上下文管理的核心逻辑 ---
    def get_databases(self) -> Tuple[bool, Union[List[str], str]]:
        """获取所有DolphinDB数据库的列表。"""
        script = "getClusterDFSDatabases()"
        exec_result = self.agent_core.code_executor.run(script)
        if exec_result.success:
            return True, exec_result.data.tolist()
        else:
            return False, exec_result.error_message

    def get_tables(self, db_path: str) -> Tuple[bool, Union[List[str], str]]:
        """获取指定数据库下的表列表。"""
        script = f'database("{db_path}").getTables()'
        exec_result = self.agent_core.code_executor.run(script)
        if exec_result.success:
            return True, exec_result.data.tolist()
        else:
            return False, exec_result.error_message

    def get_schema_for_tables(self, table_paths: List[str]) -> Tuple[bool, Union[Dict[str, pd.DataFrame], str]]:
        """获取一个或多个表的Schema。"""
        schemas = {}
        for path in table_paths:
            # 解析路径 dfs://db_name/table_name
            parts = path.replace("dfs://", "").split("/")
            if len(parts) != 2:
                return False, f"Invalid table path format: {path}"
            db_name, table_name = parts
            script = f"schema(loadTable('dfs://{db_name}', '{table_name}'))['colDefs']"
            exec_result = self.agent_core.code_executor.run(script)
            if exec_result.success:
                schemas[path] = exec_result.data
            else:
                return False, f"Failed to get schema for {path}: {exec_result.error_message}"
        return True, schemas

    def _format_schemas_as_markdown(self, schemas: Dict[str, pd.DataFrame]) -> str:
        """将Schema字典格式化为美观的Markdown文本。"""
        markdown_parts = [
            "<INJECTED_CONTEXT>",
            "The user has injected the following table schemas into the context. Use this information for all subsequent queries.\n"
        ]
        for path, schema_df in schemas.items():
            markdown_parts.append(f"### Schema for: `{path}`")
            if isinstance(schema_df, pd.DataFrame):
                # 将DataFrame转换为Markdown表格
                markdown_parts.append(schema_df.to_markdown(index=False))
            else:
                markdown_parts.append(f"Could not display schema: {str(schema_df)}")
            markdown_parts.append("\n")
        
        markdown_parts.append("</INJECTED_CONTEXT>")
        return "\n".join(markdown_parts)

    def _get_sql_executor(self) -> Optional[InteractiveSQLExecutor]:
        """Helper to safely get the executor instance."""
        executor = getattr(self.agent_core, 'interactive_sql_executor', None)
        if isinstance(executor, InteractiveSQLExecutor):
            return executor
        return None
    
    def tui_handle_direct_injection(self, path: str) -> Tuple[bool, str]:
        """
        处理直接注入的逻辑。
        自动判断路径是数据库还是表。
        """
        executor = self._get_sql_executor()
        if not executor:
            return False, "SQL Executor not available. Are you in a /sql session?"

        # 规范化路径
        if not path.startswith("dfs://"):
            return False, "Invalid path. Path must start with 'dfs://'."

        table_paths_to_inject = []

        # 尝试将路径作为数据库处理
        is_db, tables_or_error = self.get_tables(path)
        
        if is_db and isinstance(tables_or_error, list):
            # 成功，说明 path 是一个数据库
            if not tables_or_error:
                return False, f"Database `{path}` is empty or does not exist."
            # 获取该数据库下所有表的完整路径
            table_paths_to_inject.extend([f"{path.strip('/')}/{table_name}" for table_name in tables_or_error])
        else:
            # 失败，我们假设 path 可能是一个表的路径
            # 验证路径格式是否像一个表
            parts = path.replace("dfs://", "").split("/")
            if len(parts) == 2:
                table_paths_to_inject.append(path)
            else:
                # 既不是有效的数据库，也不是有效的表路径格式
                return False, f"Path `{path}` is not a valid database or table path. Error when treating as DB: {tables_or_error}"

        if not table_paths_to_inject:
             return False, "No valid tables found to inject."

        # 获取所有目标表的 Schema
        success, schemas_or_error = self.get_schema_for_tables(table_paths_to_inject)
        if not success:
            return False, schemas_or_error
        
        # 格式化并保存到session
        session_data = self.session_manager.load_session_data(self.active_session_id)
        
        # 使用 setdefault 确保顶级键存在，而不会覆盖
        session_data.setdefault('injected_context', {})
        
        # 直接设置 'schemas' 子键
        session_data['injected_context']['schemas'] = {
            "markdown": self._format_schemas_as_markdown(schemas_or_error),
            "source_paths": table_paths_to_inject
        }
        self.session_manager.save_session_data(self.active_session_id, session_data)
        
        return True, f"Successfully saved schema context for: {', '.join(table_paths_to_inject)}"


    def tui_handle_use_command_start(self) -> Tuple[bool, Union[List[str], str]]:
        """第一步：获取数据库列表给TUI展示。"""
        return self.get_databases()

    def tui_handle_use_command_db_selected(self, db_path: str) -> Tuple[bool, Union[List[str], str]]:
        """第二步：获取表列表给TUI展示。"""
        return self.get_tables(db_path)

    def tui_handle_use_command_tables_selected(self, db_path: str, table_names: List[str]) -> Tuple[bool, str]:
        """第三步：获取Schemas，注入上下文，并返回确认信息。"""
        executor = self._get_sql_executor()
        if not executor:
            return False, "SQL Executor not available. Are you in a /sql session?"

        table_paths = [f"{db_path}/{name}" for name in table_names]
        success, result = self.get_schema_for_tables(table_paths)
        
        if not success:
            return False, result # result is error message

        # 格式化并注入
        session_data = self.session_manager.load_session_data(self.active_session_id)
        session_data.setdefault('injected_context', {})
        session_data['injected_context']['schemas'] = {
            "markdown": self._format_schemas_as_markdown(result),
            "source_paths": table_paths
        }
        self.session_manager.save_session_data(self.active_session_id, session_data)
        
        
        return True, f"Successfully injected schemas for: {', '.join(table_paths)}"

    def tui_handle_context_show(self) -> str:
        """
        获取并格式化当前会话中所有注入的上下文（包括数据库表和文件）。
        """
        session_data = self.session_manager.load_session_data(self.active_session_id)
        injected_context = session_data.get('injected_context', {})
        
        schemas_context = injected_context.get('schemas', {})
        files_context = injected_context.get('files', {})

        if not schemas_context and not files_context:
            return "No context has been saved to the current session."

        markdown_parts = []

        # 1. 格式化并添加数据库表信息
        if schemas_context:
            markdown_parts.append("\n**Database Tables (from /use):**")
            source_paths = schemas_context.get('source_paths', [])
            if source_paths:
                for path in source_paths:
                    markdown_parts.append(f"- `{path}`")
            else:
                markdown_parts.append("- *No database tables have been loaded.*")

        # 2. 格式化并添加文件信息
        if files_context:
            markdown_parts.append("\n**Loaded Files (from @):**")
            if files_context:
                for path, data in files_context.items():
                    # 提取元信息用于展示
                    load_type = data.get('type', 'N/A').replace('_', ' ').title()
                    tokens = data.get('tokens', '?')
                    info = f"({load_type}, {tokens} tokens)"
                    markdown_parts.append(f"- `{path}`  `{info}`")
            else:
                markdown_parts.append("- *No files have been loaded.*")

        return "\n".join(markdown_parts)

    def tui_handle_context_clear(self,  args: List[str]) -> str:
        session_data = self.session_manager.load_session_data(self.active_session_id)
        if 'injected_context' not in session_data:
            return "No saved context to clear."

        # 默认行为是全部清除
        clear_all = '--all' in args or len(args) == 0
        clear_schemas = '--schemas' in args or clear_all
        clear_files = '--files' in args or clear_all
        
        cleared_parts = []
        if clear_schemas and 'schemas' in session_data['injected_context']:
            del session_data['injected_context']['schemas']
            cleared_parts.append("database schemas")
        
        if clear_files and 'files' in session_data['injected_context']:
            del session_data['injected_context']['files']
            cleared_parts.append("loaded files")

        # 如果清空后 injected_context 为空，则移除它
        if not session_data['injected_context']:
            del session_data['injected_context']

        if not cleared_parts:
            return "Nothing to clear with the specified flags."

        self.session_manager.save_session_data(self.active_session_id, session_data)
        return f"Successfully cleared context for: {', '.join(cleared_parts)}."

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
        
        injected_context = session_data.get('injected_context', {})
        
        # 4. 调用无状态核心执行任务
        # 注意：这里 user_input 也被传入，因为 executor 的逻辑需要它
        final_history = yield from self.agent_core.run_interactive_sql_task(user_input, contextual_history, injected_context)
        
       

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