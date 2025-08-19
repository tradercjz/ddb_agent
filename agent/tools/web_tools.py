import os
import requests
import json
from pydantic import Field

from agent.execution_result import ExecutionResult 
from .tool_interface import BaseTool, ToolInput

# 1. 定义工具的输入参数
class BaiduSearchInput(ToolInput):
    """Input model for the Baidu AI Search tool."""
    query: str = Field(description="The search query, e.g., '顺络电子基本面' or 'NVIDIA financial report'.")

# 2. 创建工具类
class BaiduSearchTool(BaseTool):
    """
    A tool to search the web using Baidu Qianfan AI Search.
    """
    name = "baidu_ai_search"
    description = (
        "Searches the web using Baidu Qianfan AI Search. "
        "Ideal for finding financial data, news, and fundamental analysis, especially for the Chinese market. "
        "Use this to get up-to-date information that is not in the local database."
    )
    args_schema = BaiduSearchInput

    def run(self, args: BaiduSearchInput) -> ExecutionResult:
        """
        Executes the Baidu AI Search and returns the result.
        """
        # 从环境变量中安全地获取 Bearer Token
        bearer_token = os.getenv("BAIDU_QIANFAN_TOKEN")
        if not bearer_token:
            return ExecutionResult(
                success=False,
                error_message="BAIDU_QIANFAN_TOKEN environment variable is not set. The administrator needs to configure it."
            )

        url = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"

        payload = json.dumps({
            "messages": [{"role": "user", "content": args.query}],
            "search_source": "baidu_search_v2",
            "search_recency_filter": "week"
        }, ensure_ascii=False)

        headers = {
            'Authorization': f'Bearer {bearer_token}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.request("POST", url, headers=headers, data=payload.encode("utf-8"))
            response.raise_for_status()  # 检查HTTP错误 (e.g., 401, 403, 500)
            
            response_data = response.json()
            
            # 提取关键结果给 Agent
            # 您可以根据需要调整返回给Agent的数据结构
            processed_data = {
                "summary": response_data.get("result", "No summary found."),
                "raw_response": response_data # 也可以包含完整响应供Agent参考
            }
            
            return ExecutionResult(
                success=True,
                data=processed_data
            )
        except requests.exceptions.HTTPError as http_err:
             return ExecutionResult(success=False, error_message=f"HTTP error occurred: {http_err} - Response: {response.text}")
        except requests.exceptions.RequestException as e:
            return ExecutionResult(success=False, error_message=f"API request failed: {e}")
        except json.JSONDecodeError:
            return ExecutionResult(success=False, error_message=f"Failed to decode API response. Raw response: {response.text}")