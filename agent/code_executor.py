# file: agent/code_executor.py

import os
import time
from typing import Optional
from dotenv import load_dotenv

from agent.execution_result import ExecutionResult
from db.database_session import DatabaseSession # 假设您的文件路径是这样

# 加载环境变量，以便安全地获取数据库凭证
load_dotenv()

class CodeExecutor:
    """
    Safely executes DolphinDB scripts and returns structured results.
    It encapsulates the database session management.
    """
    def __init__(self, 
                 host: Optional[str] = None, 
                 port: Optional[int] = None, 
                 user: Optional[str] = None, 
                 password: Optional[str] = None, 
                 logger=None):
        """
        Initializes the CodeExecutor. Credentials can be passed directly or
        loaded from environment variables (DDB_HOST, DDB_PORT, DDB_USER, DDB_PASSWORD).
        """
        self.host = host or os.getenv("DDB_HOST")
        self.port = port or int(os.getenv("DDB_PORT", "8848")) # Provide a default port
        self.user = user or os.getenv("DDB_USER", "admin")
        self.password = password or os.getenv("DDB_PASSWORD", "123456") #
        self.logger = logger

        if not all([self.host, self.port, self.user, self.password]):
            raise ValueError(
                "DolphinDB connection details are missing. "
                "Please provide them as arguments or set environment variables."
            )

        if self.logger:
            self.logger.info(f"CodeExecutor initialized for DolphinDB at {self.host}:{self.port}")

    def run(self, script: str) -> ExecutionResult:
        """
        Executes a DolphinDB script and captures its output or error.

        Args:
            script: The DolphinDB script to execute.

        Returns:
            An ExecutionResult object containing the outcome.
        """
        if not script or not script.strip():
            return ExecutionResult(
                success=False,
                error_message="Error: Empty script provided."
            )

        if self.logger:
            self.logger.info("Executing DolphinDB script...")
            # For security, you might want to log only a snippet of the script
            self.logger.debug(f"Script to run:\n---\n{script[:500]}...\n---")

        start_time = time.time()
        
        try:
            # 使用 `with` 语句来自动管理 session 的连接和关闭
            with DatabaseSession(self.host, self.port, self.user, self.password, logger=self.logger) as db_session:
                success, result = db_session.execute(script)
            
            end_time = time.time()
            duration = end_time - start_time

            if success:
                if self.logger:
                    self.logger.info(f"Script executed successfully in {duration:.2f} seconds.")
                return ExecutionResult(
                    success=True,
                    data=result,
                    metadata={"execution_duration_seconds": duration}
                )
            else:
                # `db_session.execute` 已经将异常转换为字符串
                error_str = str(result)
                if self.logger:
                    self.logger.warning(f"Script execution failed after {duration:.2f} seconds. Error: {error_str}")
                return ExecutionResult(
                    success=False,
                    error_message=error_str,
                    metadata={"execution_duration_seconds": duration}
                )

        except Exception as e:
            # 这是一个兜底的异常捕获，以防 DatabaseSession 本身出现问题（比如连接失败）
            end_time = time.time()
            duration = end_time - start_time
            error_msg = f"A critical error occurred in CodeExecutor: {str(e)}"
            if self.logger:
                self.logger.error(error_msg, exc_info=True)
            return ExecutionResult(
                success=False,
                error_message=error_msg,
                metadata={"execution_duration_seconds": duration}
            )