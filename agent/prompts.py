# file: agent/prompts.py

from typing import List, Dict
from llm.llm_prompt import llm

# 这个文件将存放所有与 Coding Agent 任务相关的 prompts

@llm.prompt(model="deepseek-reasoner") # 我们可以为代码任务指定一个更擅长编码的模型
def generate_initial_script(user_query: str, rag_context: str) -> str:
    """
    You are a world-class DolphinDB expert developer. Your task is to write a DolphinDB script to solve the user's request.

    ## User Request
    {{ user_query }}

    ## Relevant Context from Documentation
    Based on my knowledge base, here is some context that might be helpful:
    <CONTEXT>
    {{ rag_context }}
    </CONTEXT>

    ## Your Task
    - Write a complete, executable DolphinDB script that directly addresses the user's request.
    - **Do not** add any explanations, comments, or markdown formatting around the code.
    - Your output must be **only the raw script code**.
    - ensure the output not wrappered in any code block or markdown formatting.
    """
    pass


@llm.prompt(model="deepseek-reasoner") # 同样使用编码模型
def fix_script_from_error(
    original_query: str,
    failed_code: str,
    error_message: str,
    rag_context: str,
    # (可选) 增加一个 full_history 字段，提供完整的尝试历史
    # full_history: str 
) -> str:
    """
    You are an elite DolphinDB debugging expert. You previously wrote a script that failed to execute. Your task is to analyze the error and provide a corrected version of the script.

    ## Original User Request
    {{ original_query }}

    ## Context from Documentation
    <CONTEXT>
    {{ rag_context }}
    </CONTEXT>

    ## The Code That Failed
    The following script was executed:
    ```dolphiindb
    {{ failed_code }}
    ```

    ## Execution Error
    It failed with the following error message:
    ```
    {{ error_message }}
    ```

    ## Your Task
    1.  Carefully analyze the error message in the context of the code and the original request.
    2.  Identify the root cause of the error.
    3.  Provide a new, complete, and corrected version of the script.
    4.  **Do not** add any explanations or markdown. Your output must be **only the raw, fixed script code**.
    """
    pass

@llm.prompt(model="deepseek") # Planner需要最强的模型
def debugging_planner(
    original_query: str,
    failed_code: str,
    error_message: str,
    tool_definitions: str,
    # 也可以加入对话历史、RAG上下文等
) -> str:
    """
    You are an autonomous debugging expert for DolphinDB.
    A script you wrote has failed. Your goal is to create a step-by-step plan to identify the cause of the error and fix the script.

    ## Initial Goal
    The user wants to: {{ original_query }}

    ## The Code that Failed
    ```dolphiindb
    {{ failed_code }}
    ```

    ## The Error Message
    ```
    {{ error_message }}
    ```

    ## Available Tools
    You have access to the following tools to help you diagnose the problem.
    {{ tool_definitions }}

    ## Your Task
    Based on the error, create a JSON plan of actions to take.
    - Think step-by-step.
    - The plan should lead to a final, corrected script.
    - The available actions are the names of the tools provided.
    - The final step in your plan should ALWAYS be `run_dolphindb_script` with the fully corrected code.

    Example Plan for a function error:
    ```json
    [
      {
        "step": 1,
        "thought": "The error message 'wavg function needs 2 argument(s)' suggests I used the wavg function incorrectly. I need to check its correct signature and documentation.",
        "action": "get_function_signature",
        "args": {"function_name": "wavg"}
      },
      {
        "step": 2,
        "thought": "The documentation shows wavg requires two arguments: a value column and a weight column. The original code only provided one. I need to add the 'qty' column as the weight. I will now construct the corrected script and run it.",
        "action": "run_dolphindb_script",
        "args": {"script": "trades = stocks::create_mock_trades_table()\nselect wavg(price, qty) from trades"}
      }
    ]
    ```
    """
    pass