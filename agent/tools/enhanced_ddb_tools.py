# file: agent/tools/enhanced_ddb_tools.py

import dolphindb as ddb
from pydantic import Field, field_validator
from typing import List, Dict, Any, Optional
import json
import os

from agent.execution_result import ExecutionResult 
from .tool_interface import BaseTool, ToolInput
from agent.code_executor import CodeExecutor


class InspectDatabaseInput(ToolInput):
    """检查数据库连接和基本信息"""
    pass


class InspectDatabaseTool(BaseTool):
    name = "inspect_database"
    description = "Check database connection status and get basic system information like version, memory usage, and available databases."
    args_schema = InspectDatabaseInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: InspectDatabaseInput) -> ExecutionResult:
        """检查数据库状态"""
        inspection_script = """
        // Database inspection script
        info = dict(STRING, ANY)
        info["version"] = version()
        info["license"] = license()
        info["node_count"] = getClusterPerf().size()
        info["databases"] =  getClusterDFSDatabases()
      
        info
        """
        
        result = self.executor.run(inspection_script)
        return result

class ListTablesInput(ToolInput):
    database_name: Optional[str] = Field(default=None, description="Database name to list tables from. If not provided, lists tables from current session.")
    pattern: Optional[str] = Field(default=None, description="Pattern to filter table names (SQL LIKE pattern)")


class ListTablesTool(BaseTool):
    name = "list_tables"
    description = "List all tables in a database or current session, optionally filtered by pattern."
    args_schema = ListTablesInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: ListTablesInput) -> ExecutionResult:
        if args.database_name:
            script = f"""
            database("{args.database_name}").listTables()
            """
        else:
            script = """
            // List tables in current session
            objs = objs(true)
            tables = select name, type, form from objs where type="TABLE"
            tables
            """
        
        result = self.executor.run(script)
        return result


class DescribeTableInput(ToolInput):
    table_name: str = Field(description="Name of the table to describe")
    database_name: Optional[str] = Field(default=None, description="Database name if table is in a specific database")


class DescribeTableTool(BaseTool):
    name = "describe_table"
    description = "Get detailed schema information about a table including column names, types, and sample data."
    args_schema = DescribeTableInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: DescribeTableInput) -> ExecutionResult:
        if args.database_name:
            table_ref = f'database("{args.database_name}").loadTable("{args.table_name}")'
        else:
            table_ref = args.table_name
        
        script = f"""
        // Describe table structure and sample data
        t = {table_ref}
        
        result = dict(STRING, ANY)
        result["table_name"] = "{args.table_name}"
        result["schema"] = schema(t)
        result["column_count"] = t.columns().size()
        result["row_count"] = t.size()
        
        // Get sample data (first 5 rows)
        try {{
            result["sample_data"] = select top 5 * from t
        }} catch(ex) {{
            result["sample_data"] = "Unable to fetch sample data: " + ex
        }}
        
        result
        """
        
        result = self.executor.run(script)
        return result


class ValidateScriptInput(ToolInput):
    script: str = Field(description="DolphinDB script to validate for syntax errors")


class ValidateScriptTool(BaseTool):
    name = "validate_script"
    description = "Check a DolphinDB script for syntax errors without executing it."
    args_schema = ValidateScriptInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: ValidateScriptInput) -> ExecutionResult:
        # DolphinDB doesn't have a built-in syntax validator, so we'll try to parse it
        validation_script = f"""
        try {{
            parseExpr(`{args.script.replace('`', '``')})
            "Script syntax is valid"
        }} catch(ex) {{
            "Syntax error: " + ex
        }}
        """
        
        result = self.executor.run(validation_script)
        return result


class QueryDataInput(ToolInput):
    query: str = Field(description="SQL query to execute")
    limit: Optional[int] = Field(default=100, description="Maximum number of rows to return")


class QueryDataTool(BaseTool):
    name = "query_data"
    description = "Execute a SELECT query and return results with optional row limit."
    args_schema = QueryDataInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: QueryDataInput) -> ExecutionResult:
        # Add limit to query if not already present
        query = args.query.strip()
        # if args.limit and not query.lower().startswith('select top'):
        #     if query.lower().startswith('select'):
        #         query = query.replace('select', f'select top {args.limit}', 1)
        
        result = self.executor.run(query)
        return result


class CreateSampleDataInput(ToolInput):
    data_type: str = Field(description="Type of sample data to create (e.g., 'trades', 'quotes', 'timeseries')")
    row_count: Optional[int] = Field(default=1000, description="Number of rows to generate")
    table_name: Optional[str] = Field(default=None, description="Name for the created table")


class CreateSampleDataTool(BaseTool):
    name = "create_sample_data"
    description = "Create sample data for testing purposes. Supports common financial data types."
    args_schema = CreateSampleDataInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: CreateSampleDataInput) -> ExecutionResult:
        table_name = args.table_name or f"sample_{args.data_type}"
        
        if args.data_type.lower() == "trades":
            script = f"""
            // Create sample trades data
            n = {args.row_count}
            symbols = `AAPL`MSFT`GOOGL`AMZN`TSLA
            {table_name} = table(
                take(symbols, n) as symbol,
                2023.01.01T09:30:00.000 + rand(6.5*60*60*1000, n) as timestamp,
                20.0 + rand(100.0, n) as price,
                100 + rand(1000, n) as qty,
                rand(`B`S, n) as side
            )
            select count(*) as row_count from {table_name}
            """
        elif args.data_type.lower() == "quotes":
            script = f"""
            // Create sample quotes data
            n = {args.row_count}
            symbols = `AAPL`MSFT`GOOGL`AMZN`TSLA
            {table_name} = table(
                take(symbols, n) as symbol,
                2023.01.01T09:30:00.000 + rand(6.5*60*60*1000, n) as timestamp,
                20.0 + rand(100.0, n) as bid_price,
                20.1 + rand(100.0, n) as ask_price,
                100 + rand(1000, n) as bid_size,
                100 + rand(1000, n) as ask_size
            )
            select count(*) as row_count from {table_name}
            """
        elif args.data_type.lower() == "timeseries":
            script = f"""
            // Create sample time series data
            n = {args.row_count}
            {table_name} = table(
                2023.01.01T00:00:00.000 + (0..(n-1)) * 60000 as timestamp,
                100.0 + cumsum(rand(2.0, n) - 1.0) as value,
                rand(10.0, n) as volume
            )
            select count(*) as row_count from {table_name}
            """
        else:
            return f"Unsupported data type: {args.data_type}. Supported types: trades, quotes, timeseries"
        
        result = self.executor.run(script)
        return result


class OptimizeQueryInput(ToolInput):
    query: str = Field(description="Query to analyze and optimize")


class OptimizeQueryTool(BaseTool):
    name = "optimize_query"
    description = "Analyze a query and suggest optimizations for better performance."
    args_schema = OptimizeQueryInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    def run(self, args: OptimizeQueryInput) -> ExecutionResult:
        # This is a simplified optimization analyzer
        # In practice, you might want to use DolphinDB's query plan analysis
        
        analysis_script = f"""
        // Basic query analysis
        query_text = `{args.query.replace('`', '``')}`
        
        analysis = dict(STRING, ANY)
        analysis["original_query"] = query_text
        
        // Check for common optimization opportunities
        suggestions = string[]
        
        if(query_text.regexFind("select \\\\* from") != -1)
            suggestions.append!("Consider selecting only needed columns instead of SELECT *")
        
        if(query_text.regexFind("where.*=.*or.*=") != -1)
            suggestions.append!("Consider using IN clause instead of multiple OR conditions")
        
        if(query_text.regexFind("order by") != -1 && query_text.regexFind("limit|top") == -1)
            suggestions.append!("Consider adding LIMIT/TOP clause when using ORDER BY")
        
        analysis["suggestions"] = suggestions
        analysis["query_length"] = query_text.size()
        
        analysis
        """
        
        result = self.executor.run(analysis_script)
        return result
        

class GetFunctionDocumentationInput(ToolInput):
    """Input model for the function documentation tool."""
    function_name: str = Field(description="The name of the DolphinDB function to look up documentation for. Should not be empty.")

    # Pydantic v2 的写法
    @field_validator('function_name')
    @classmethod
    def function_name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('function_name must not be empty')
        return v

class GetFunctionDocumentationTool(BaseTool):
    """
    A tool to retrieve detailed documentation for a specific DolphinDB function.
    """
    name = "get_function_documentation"
    description = (
        "Retrieves the full documentation for a specific DolphinDB function from the knowledge base. "
        "Use this when you are unsure about a function's arguments, behavior, or see an error message "
        "related to a specific function call (e.g., 'wrong number of arguments')."
    )
    args_schema = GetFunctionDocumentationInput

    def __init__(self, project_path: str):
        """
        Initializes the tool.
        
        Args:
            project_path: The root path of the project, used to locate the 'documentation/funcs' folder.
        """
        # 路径现在指向 funcs 子目录
        self.base_doc_path = os.path.join(project_path, "documentation", "funcs")

    def run(self, args: GetFunctionDocumentationInput) -> ExecutionResult:
        """
        Reads and returns the content of a function's documentation file 
        from the structured directory: documentation/funcs/{first_char}/{function_name}.md
        """
        function_name = args.function_name.strip()

        # 1. 获取函数名的首字母
        first_char = function_name[0].lower()
        
        # 2. 检查首字母是否是合法的目录名 (例如，a-z)
        if not 'a' <= first_char <= 'z':
            return f"Error: Invalid function name '{function_name}'. It must start with a letter."

        # 3. 构造完整的文件路径
        #    函数名本身也统一转为小写，以匹配文件名
        doc_file_path = os.path.join(self.base_doc_path, first_char, f"{function_name.lower()}.md")

        # 4. 检查文件是否存在
        if not os.path.exists(doc_file_path):
            # 可以提供更友好的提示，比如建议Agent检查函数名拼写
            return (
                f"Error: Documentation for function '{function_name}' not found. "
                f"Searched at: '{doc_file_path}'. "
                "Please ensure the function name is spelled correctly."
            )

        try:
            # 5. 读取文件内容
            with open(doc_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 6. 检查文件内容是否为空
            if not content or not content.strip():
                return (
                    f"Warning: Documentation for function '{function_name}' was found, "
                    "but the file is empty. No details are available."
                )

            return ExecutionResult(
                success=True,
                executed_script=f"Documentation for function '{function_name}' retrieved successfully.",
                data=(
                f"--- Documentation for {function_name} ---\n\n"
                f"{content}\n\n"
                f"--- End of Documentation ---"
            )
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                executed_script=f"Failed to read documentation for function '{function_name}'.",
                error_message=str(e)
            )