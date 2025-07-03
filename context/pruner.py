# file: ddb_agent/context/pruner.py

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import json
from llm.llm_prompt import llm
from utils.json_parser import parse_json_string 
class SourceCode:
    """A simple container for source code data."""
    def __init__(self, module_name: str, source_code: str, tokens: int = -1):
        self.module_name = module_name
        self.source_code = source_code
        # 懒加载token计数，如果未提供
        from token_counter import count_tokens # 局部导入避免循环依赖
        self.tokens = tokens if tokens != -1 else count_tokens(source_code)

class BasePruner(ABC):
    """
    Abstract base class for all context pruning strategies.
    """
    def __init__(self, max_tokens: int):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer.")
        self.max_tokens = max_tokens

    @abstractmethod
    def prune(
        self, 
        file_sources: List[SourceCode], 
        conversations: List[Dict[str, Any]]
    ) -> List[SourceCode]:
        """
        Applies a specific pruning strategy to the list of file sources.

        Args:
            file_sources: A list of SourceCode objects to be pruned.
            conversations: The conversation history, which may be used by the strategy.

        Returns:
            A pruned list of SourceCode objects that fits within max_tokens.
        """
        pass

    def _count_total_tokens(self, sources: List[SourceCode]) -> int:
        """Helper method to count total tokens of a list of sources."""
        return sum(source.tokens for source in sources)
    

class DeletePruner(BasePruner):
    """
    A simple pruner that discards files from the end of the list 
    if the total token count exceeds the limit.
    It assumes the input file_sources list is already sorted by importance.
    """
    def prune(
        self, 
        file_sources: List[SourceCode], 
        conversations: List[Dict[str, Any]]
    ) -> List[SourceCode]:
        
        print("Applying 'delete' pruning strategy...")
        
        total_tokens = self._count_total_tokens(file_sources)
        if total_tokens <= self.max_tokens:
            return file_sources

        pruned_sources: List[SourceCode] = []
        current_tokens = 0

        for source in file_sources:
            if current_tokens + source.tokens <= self.max_tokens:
                pruned_sources.append(source)
                current_tokens += source.tokens
            else:
                print(f"Token limit reached. Discarding remaining files starting from {source.module_name}.")
                break
        
        print(f"Pruning complete. Kept {len(pruned_sources)} files with {current_tokens} tokens.")
        return pruned_sources


class ExtractPruner(BasePruner):
    """
    An intelligent pruner that extracts relevant code snippets from large files.
    """
    def __init__(self, max_tokens: int, llm_model_name: str = "deepseek-default", max_workers = 8):
        super().__init__(max_tokens)
        self.llm_model_name = llm_model_name
        self.full_file_threshold = int(max_tokens * 0.8)
        self.max_workers = max_workers

    @llm.prompt()
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
      

    def _merge_overlapping_snippets(self, snippets: List[Dict[str, int]]) -> List[Dict[str, int]]:
        """...""" # 实现不变
        if not snippets: return []
        sorted_snippets = sorted(snippets, key=lambda x: x["start_line"])
        merged = [sorted_snippets[0]]
        for current in sorted_snippets[1:]:
            last = merged[-1]
            if current["start_line"] <= last["end_line"] + 1:
                last["end_line"] = max(last["end_line"], current["end_line"])
            else:
                merged.append(current)
        return merged

    def _build_snippet_content(self, original_code: str, snippets: List[Dict[str, int]]) -> str:
        """...""" # 实现不变
        lines = original_code.splitlines()
        content_parts = ["# Snippets from the original file:\n"]
        for snippet in snippets:
            start = max(0, snippet["start_line"] - 1)
            end = min(len(lines), snippet["end_line"])
            content_parts.append(f"\n# ... (lines {start + 1}-{end}) ...\n")
            content_parts.extend(lines[start:end])
        return "\n".join(content_parts)

    def _process_single_large_file(self, file_source: SourceCode, conversations: List[Dict[str, Any]]) -> SourceCode:
        """
        Processes a single large file to extract snippets. This is the target for our threads.
        Returns a new SourceCode object with pruned content, or the original if it fails.
        """
        print(f"  - Starting snippet extraction for: {file_source.module_name}")
        try:
            lines_with_numbers = "\n".join(
                f"{i+1} {line}" for i, line in enumerate(file_source.source_code.splitlines())
            )
            
            response_str = self._extract_snippets_prompt(
                conversations=conversations,
                content_with_lines=lines_with_numbers
            )
            
            raw_snippets = parse_json_string(response_str)
            
            if not raw_snippets:
                print(f"  - No relevant snippets found in {file_source.module_name}.")
                # 返回一个空内容的SourceCode，但保留文件名，token为0
                return SourceCode(file_source.module_name, "", 0)
            
            merged_snippets = self._merge_overlapping_snippets(raw_snippets)
            new_content = self._build_snippet_content(file_source.source_code, merged_snippets)

            # 返回一个新的、内容被精简的SourceCode对象
            return SourceCode(file_source.module_name, new_content)
        except Exception as e:
            print(f"  - Error extracting snippets from {file_source.module_name}: {e}. Keeping original content for now.")
            # 如果处理失败，可以返回原始对象或一个空对象，这里选择返回空对象以强制其被丢弃（如果token超限）
            return SourceCode(file_source.module_name, "", 0)

    def prune(
        self, 
        file_sources: List[SourceCode], 
        conversations: List[Dict[str, Any]]
    ) -> List[SourceCode]:
        
        print(f"Applying concurrent 'extract' pruning strategy with {self.max_workers} workers...")
        
        # 1. 分组：小文件 vs 大文件
        small_files: List[SourceCode] = []
        large_files: List[SourceCode] = []
        
        current_tokens = 0
        for source in file_sources:
            if current_tokens + source.tokens <= self.full_file_threshold:
                small_files.append(source)
                current_tokens += source.tokens
            else:
                large_files.append(source)
        
        # print(f"Split files: {len(small_files)} small files (kept whole), {len(large_files)} large files (to be processed).")
        

        # 测试
        large_files += small_files  # 确保小文件也在后续处理列表中
        # 2. 并发处理大文件
        processed_large_files: List[SourceCode] = []
        if large_files:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_source = {
                    executor.submit(self._process_single_large_file, source, conversations): source 
                    for source in large_files
                }
                
                for future in as_completed(future_to_source):
                    try:
                        processed_source = future.result()
                        if processed_source.tokens > 0: # 只保留有内容的
                            processed_large_files.append(processed_source)
                    except Exception as exc:
                        original_source = future_to_source[future]
                        print(f"Exception processing {original_source.module_name}: {exc}")

        # 3. 合并和最终剪枝
        # 将完整保留的小文件和处理后的大文件片段合并
        # 我们优先保留小文件，然后尝试添加处理后的大文件片段
        print("Merging results and performing final token check...")
        final_sources: List[SourceCode] = []
        # final_tokens = self._count_total_tokens(small_files)
        # final_sources.extend(small_files)

        final_tokens = 0

        # 对处理后的大文件按（新）token数从小到大排序，优先添加小的
        processed_large_files.sort(key=lambda x: x.tokens)

        for source in processed_large_files:
            if final_tokens + source.tokens <= self.max_tokens:
                final_sources.append(source)
                final_tokens += source.tokens
                print(f"  - Added snippets from {source.module_name} ({source.tokens} tokens)")
            else:
                print(f"  - Snippets from {source.module_name} ({source.tokens} tokens) too large to fit. Discarding.")
        
        print(f"Pruning complete. Final context has {len(final_sources)} files with {final_tokens} tokens.")
        return final_sources



def get_pruner(strategy: str, max_tokens: int, **kwargs) -> BasePruner:
    """
    Factory function to get a pruner instance based on the strategy name.

    Args:
        strategy: The name of the strategy ('delete', 'extract').
        max_tokens: The maximum number of tokens allowed.
        **kwargs: Additional arguments for specific pruners (e.g., llm_model_name).

    Returns:
        An instance of a BasePruner subclass.
    """
    if strategy == "delete":
        return DeletePruner(max_tokens=max_tokens)
    elif strategy == "extract":
        return ExtractPruner(max_tokens=max_tokens, **kwargs)
    # 未来可以扩展
    # elif strategy == "summarize":
    #     return SummarizePruner(max_tokens=max_tokens, **kwargs)
    else:
        raise ValueError(f"Unknown pruning strategy: {strategy}. "
                         "Available strategies: 'delete', 'extract'.")