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