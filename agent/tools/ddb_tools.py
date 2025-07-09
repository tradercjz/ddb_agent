# file: agent/tools/ddb_tools.py (新建)
import dolphindb as ddb
from pydantic import Field # 假设可以这样导入
from .tool_interface import BaseTool, ToolInput
from agent.code_executor import CodeExecutor 

class GetFunctionSignatureInput(ToolInput):
    function_name: str = Field(description="The name of the DolphinDB function to look up.")

class GetFunctionSignatureTool(BaseTool):
    name = "get_function_signature"
    description = "Retrieves the definition and documentation of a specific DolphinDB function. Use this when you encounter an error related to a function call, like wrong number of arguments or unknown function."
    args_schema = GetFunctionSignatureInput
    
    # 我们需要一个DDB session来执行'help'命令
    # 这里的实现是简化的，实际中可能需要从CodeExecutor传入session
    _session = ddb.session() 
    # _session.connect(...)

    def run(self, args: GetFunctionSignatureInput) -> str:
        try:
            # DolphinDB的 `help` 函数可以获取函数定义
            result = self._session.run(f"help({args.function_name})")
            return str(result)
        except Exception as e:
            return f"Error: Could not retrieve help for function '{args.function_name}'. Reason: {e}"
        
class RunDolphinDBScriptInput(ToolInput):
    script: str = Field(description="The DolphinDB script to execute.")

class RunDolphinDBScriptTool(BaseTool):
    name = "run_dolphindb_script"
    description = "Executes a given DolphinDB script. Returns the data output on success or an error message on failure."
    args_schema = RunDolphinDBScriptInput
    
    def __init__(self):
        self.executor = CodeExecutor()

    def run(self, args: RunDolphinDBScriptInput) -> str:
        result = self.executor.run(args.script)
        if result.success:
            # 将结果转换为字符串，以便LLM处理
            return f"Execution successful. Data:\n{str(result.data)}"
        else:
            return f"Execution failed. Error:\n{result.error_message}"