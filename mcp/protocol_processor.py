import json
from typing import Dict, List, Any

from .types import ProcessedToolResult
from utils.json_parser import parse_json_string

def process_mcp_tool_result(tool_result: Dict[str, Any]) -> ProcessedToolResult:
    """
    根据MCP规范 (2025-06-18版)，处理并净化从服务器返回的 ToolResult 对象。

    此函数遵循以下优先级来提取最终数据：
    1. 使用 `structuredContent` 字段（如果存在）。
    2. 如果没有，则从 `content` 列表中提取所有 text/plain 内容，
       并尝试将其解析为JSON。
    3. 如果解析失败，则将其作为纯文本。

    Args:
        tool_result (Dict[str, Any]): 代表 ToolResult 对象的 Python 字典。

    Returns:
        ProcessedToolResult: 一个包含净化后数据的标准化结果对象。
    """
    # 1. 安全地获取规范字段
    is_error = tool_result.get("isError", False)
    content_list = tool_result.get("content", [])
    structured_content = tool_result.get("structuredContent")

    # 2. 优先处理错误情况
    if is_error:
        error_message = "Tool executed with an unspecified error."
        if isinstance(content_list, list):
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    error_message = item["text"]
                    break
        return ProcessedToolResult(
            success=False,
            data=None,
            error_message=error_message,
            raw_content_list=content_list
        )

    # 3. 处理成功响应 - 优先使用 structuredContent
    if structured_content is not None:
        return ProcessedToolResult(
            success=True,
            data=structured_content,
            raw_content_list=content_list
        )

    # 4. 如果没有 structuredContent，则处理 content 列表作为备选方案
    text_parts = []
    if isinstance(content_list, list):
        for item in content_list:
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                text_parts.append(str(item["text"]))
    
    combined_text = "".join(text_parts)

    # 5. 尝试将组合后的文本解析为JSON (处理向后兼容的情况)
    if combined_text:
        try:
            # 使用 parse_json_string 以应对可能的Markdown ```json ```包裹
            parsed_data = parse_json_string(combined_text)
            if parsed_data is not None:
                return ProcessedToolResult(
                    success=True,
                    data=parsed_data,
                    raw_content_list=content_list
                )
        except (json.JSONDecodeError, TypeError):
            pass # 解析失败，说明它就是纯文本

    # 6. 如果所有尝试都失败了，或者文本为空，则返回文本本身
    return ProcessedToolResult(
        success=True,
        data=combined_text,
        raw_content_list=content_list
    )