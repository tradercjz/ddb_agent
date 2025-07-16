# file: agent/tools/enhanced_ddb_tools.py

import dolphindb as ddb
from pydantic import Field
from typing import List, Dict, Any, Optional
import json

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
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: InspectDatabaseInput) -> str:
        """检查数据库状态"""
        inspection_script = """
        // Database inspection script
        info = dict(STRING, ANY)
        info["version"] = version()
        info["license"] = license()
        info["memory_usage"] = memory()
        info["node_count"] = getClusterPerf().size()
        info["current_user"] = getCurrentUser()
        info["current_session"] = getCurrentSessionId()
        
        // Get available databases
        try {
            info["databases"] = exec sql from getClusterDFSDatabases()
        } catch(ex) {
            info["databases"] = "No DFS databases or insufficient permissions"
        }
        
        info
        """
        
        result = self.executor.run(inspection_script)
        if result.success:
            return f"Database inspection successful:\n{result.data}"
        else:
            return f"Database inspection failed: {result.error_message}"


class ListTablesInput(ToolInput):
    database_name: Optional[str] = Field(default=None, description="Database name to list tables from. If not provided, lists tables from current session.")
    pattern: Optional[str] = Field(default=None, description="Pattern to filter table names (SQL LIKE pattern)")


class ListTablesTool(BaseTool):
    name = "list_tables"
    description = "List all tables in a database or current session, optionally filtered by pattern."
    args_schema = ListTablesInput
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: ListTablesInput) -> str:
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
        if result.success:
            return f"Tables found:\n{result.data}"
        else:
            return f"Failed to list tables: {result.error_message}"


class DescribeTableInput(ToolInput):
    table_name: str = Field(description="Name of the table to describe")
    database_name: Optional[str] = Field(default=None, description="Database name if table is in a specific database")


class DescribeTableTool(BaseTool):
    name = "describe_table"
    description = "Get detailed schema information about a table including column names, types, and sample data."
    args_schema = DescribeTableInput
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: DescribeTableInput) -> str:
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
        if result.success:
            return f"Table description:\n{result.data}"
        else:
            return f"Failed to describe table: {result.error_message}"


class ValidateScriptInput(ToolInput):
    script: str = Field(description="DolphinDB script to validate for syntax errors")


class ValidateScriptTool(BaseTool):
    name = "validate_script"
    description = "Check a DolphinDB script for syntax errors without executing it."
    args_schema = ValidateScriptInput
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: ValidateScriptInput) -> str:
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
        if result.success:
            return str(result.data)
        else:
            return f"Validation failed: {result.error_message}"


class QueryDataInput(ToolInput):
    query: str = Field(description="SQL query to execute")
    limit: Optional[int] = Field(default=100, description="Maximum number of rows to return")


class QueryDataTool(BaseTool):
    name = "query_data"
    description = "Execute a SELECT query and return results with optional row limit."
    args_schema = QueryDataInput
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: QueryDataInput) -> str:
        # Add limit to query if not already present
        query = args.query.strip()
        if args.limit and not query.lower().startswith('select top'):
            if query.lower().startswith('select'):
                query = query.replace('select', f'select top {args.limit}', 1)
        
        result = self.executor.run(query)
        if result.success:
            return f"Query results:\n{result.data}"
        else:
            return f"Query failed: {result.error_message}"


class CreateSampleDataInput(ToolInput):
    data_type: str = Field(description="Type of sample data to create (e.g., 'trades', 'quotes', 'timeseries')")
    row_count: Optional[int] = Field(default=1000, description="Number of rows to generate")
    table_name: Optional[str] = Field(default=None, description="Name for the created table")


class CreateSampleDataTool(BaseTool):
    name = "create_sample_data"
    description = "Create sample data for testing purposes. Supports common financial data types."
    args_schema = CreateSampleDataInput
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: CreateSampleDataInput) -> str:
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
        if result.success:
            return f"Sample data created successfully. Table '{table_name}' with {result.data} rows."
        else:
            return f"Failed to create sample data: {result.error_message}"


class OptimizeQueryInput(ToolInput):
    query: str = Field(description="Query to analyze and optimize")


class OptimizeQueryTool(BaseTool):
    name = "optimize_query"
    description = "Analyze a query and suggest optimizations for better performance."
    args_schema = OptimizeQueryInput
    
    def __init__(self):
        self.executor = CodeExecutor()
    
    def run(self, args: OptimizeQueryInput) -> str:
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
        if result.success:
            return f"Query optimization analysis:\n{result.data}"
        else:
            return f"Failed to analyze query: {result.error_message}"