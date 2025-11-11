# file: ddb_agent/context/code_extractor_pruner.py

import os
import json
from typing import List, Dict, Any, Tuple
from llm.llm_prompt import llm  # 假设您使用之前设计的llm.prompt
from token_counter import count_tokens # 引入我们之前创建的token计数器

class Document:
    """A simple container for source code or md doc data."""
    def __init__(self, file_path: str, source_code: str, tokens: int = -1):
        self.file_path = file_path
        self.source_code = source_code
        self.tokens = tokens if tokens != -1 else count_tokens(source_code)

class CodeExtractorPruner:
    """
    Implements the 'extract' context pruning strategy.
    It extracts relevant code snippets from large files based on conversation history.
    """
    def __init__(self, max_tokens: int, llm_model_name: str = None):
        self.max_tokens = max_tokens
        # 如果未指定模型名，从环境变量读取
        self.llm_model_name = llm_model_name or os.getenv("Default_LLM_Model", "deepseek")
        # 设置一个阈值，小于此阈值的文件将被完整保留，以提高效率
        self.full_file_threshold = int(max_tokens * 0.8)

    @llm.prompt(response_model=List[Dict[str, int]])
    def _extract_snippets_prompt(self, conversations: List[Dict[str, str]], content_with_lines: str) -> dict:
        """
        Based on the provided code file and conversation history, extract relevant code snippets.

        The code file content is provided below with line numbers.
        <CODE_FILE>
        {{ content_with_lines }}
        </CODE_FILE>

        Here is the conversation history leading to the current task.
        <CONVERSATION_HISTORY>
        {% for msg in conversations %}
        <{{ msg.role }}>: {{ msg.content }}
        {% endfor %}
        </CONVERSATION_HISTORY>

        Your Task:
        1. Analyze the last user request in the conversation history.
        2. Identify one or more important code sections in the code file that are relevant to this request.
        3. For each relevant section, determine its start and end line numbers.
        4. You can return up to 4 snippets.

        Output Requirements:
        - Return a JSON array of objects, where each object contains "start_line" and "end_line".
        - Line numbers must be integers and correspond to the numbers in the provided code file.
        - If no code sections are relevant, return an empty array [].
        - Your response MUST be a valid JSON array and nothing else.

        Example output:
        ```json
        [
            {"start_line": 10, "end_line": 25},
            {"start_line": 88, "end_line": 95}
        ]
        ```
        """
        # 这个函数将使用 llm.prompt 装饰器，自动填充模板
        return {
            "model": self.llm_model_name,
            # conversations 和 content_with_lines 会从函数参数中获取
        }
    
    def _merge_overlapping_snippets(self, snippets: List[Dict[str, int]]) -> List[Dict[str, int]]:
        """Merges overlapping or adjacent line number ranges."""
        if not snippets:
            return []

        # 按起始行排序
        sorted_snippets = sorted(snippets, key=lambda x: x["start_line"])

        merged = [sorted_snippets[0]]
        for current in sorted_snippets[1:]:
            last = merged[-1]
            # 如果当前区间的开始在前一个区间的结束行+1的范围内，则合并
            if current["start_line"] <= last["end_line"] + 1:
                last["end_line"] = max(last["end_line"], current["end_line"])
            else:
                merged.append(current)
        return merged

    def _build_snippet_content(self, original_code: str, snippets: List[Dict[str, int]]) -> str:
        """Constructs the final content string from the extracted snippets."""
        lines = original_code.splitlines()
        content_parts = ["# Snippets from the original file:\n"]
        
        for snippet in snippets:
            start = max(0, snippet["start_line"] - 1)
            end = min(len(lines), snippet["end_line"])
            content_parts.append(f"\n# ... (lines {start + 1}-{end}) ...\n")
            content_parts.extend(lines[start:end])
        
        return "\n".join(content_parts)

    def prune(self, file_sources: List[Document], conversations: List[Dict[str, str]]) -> List[Document]:
        """
        Prunes the context by extracting relevant snippets from large files.
        """
        print("Starting 'extract' pruning strategy...")
        selected_files: List[Document] = []
        total_tokens = 0
        
        for file_source in file_sources:
            if total_tokens + file_source.tokens <= self.full_file_threshold:
                # 1. 完整保留小文件
                selected_files.append(file_source)
                total_tokens += file_source.tokens
                print(f"✅ Kept file completely: {file_source.file_path} ({file_source.tokens} tokens)")
                continue

            if total_tokens >= self.max_tokens:
                print("Token limit reached. Stopping further processing.")
                break

            # 2. 对大文件进行片段抽取
            print(f"🔍 Processing large file for snippets: {file_source.file_path} ({file_source.tokens} tokens)")
            
            try:
                # 为文件内容添加行号
                lines_with_numbers = "\n".join(
                    f"{i+1} {line}" for i, line in enumerate(file_source.source_code.splitlines())
                )
                
                # 调用 LLM 抽取片段
                # 注意：这里我们假设单个文件添加行号后不会超过模型窗口，
                # 如果会，则需要引入 `_split_content_with_sliding_window` 逻辑
                raw_snippets = self._extract_snippets_prompt(
                    conversations=conversations,
                    content_with_lines=lines_with_numbers
                )
                
                if not raw_snippets:
                    print(f"  - No relevant snippets found in {file_source.file_path}.")
                    continue
                
                # 合并重叠片段
                merged_snippets = self._merge_overlapping_snippets(raw_snippets)
                
                # 构建新内容并计算token
                new_content = self._build_snippet_content(file_source.source_code, merged_snippets)
                new_tokens = count_tokens(new_content, model_name=self.llm_model_name)
                
                if total_tokens + new_tokens <= self.max_tokens:
                    selected_files.append(Document(
                        file_path=file_source.file_path,
                        source_code=new_content,
                        tokens=new_tokens
                    ))
                    total_tokens += new_tokens
                    print(f"  - Extracted snippets from {file_source.file_path}. "
                          f"Original: {file_source.tokens} tokens -> New: {new_tokens} tokens.")
                else:
                    print(f"  - Snippets from {file_source.file_path} are too large to fit. Skipping.")
                    break # 如果添加片段后超限，则停止处理后续文件

            except Exception as e:
                print(f"Error processing snippets for {file_source.file_path}: {e}")
                continue # 出错则跳过此文件

        print(f"Pruning complete. Final context has {len(selected_files)} files with {total_tokens} tokens.")
        return selected_files