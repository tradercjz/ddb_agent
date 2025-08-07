# file: ddb_agent/context/pruner.py

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import json

from pydantic import BaseModel, Field, field_validator
from llm.llm_prompt import llm
from token_counter import count_tokens
from utils.json_parser import parse_json_string 
class Document:
    """A simple container for source code data."""
    def __init__(self, file_path: str, source_code: str, tokens: int = -1):
        self.file_path = file_path
        self.source_code = source_code
        # 懒加载token计数，如果未提供
        from token_counter import count_tokens # 局部导入避免循环依赖
        self.tokens = tokens if tokens != None else count_tokens(source_code)

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
        file_sources: List[Document], 
        conversations: List[Dict[str, Any]]
    ) -> List[Document]:
        """
        Applies a specific pruning strategy to the list of file sources.

        Args:
            file_sources: A list of Document objects to be pruned.
            conversations: The conversation history, which may be used by the strategy.

        Returns:
            A pruned list of Document objects that fits within max_tokens.
        """
        pass

    def _count_total_tokens(self, sources: List[Document]) -> int:
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
        file_sources: List[Document], 
        conversations: List[Dict[str, Any]]
    ) -> List[Document]:
        
        print("Applying 'delete' pruning strategy...")
        
        total_tokens = self._count_total_tokens(file_sources)
        if total_tokens <= self.max_tokens:
            return file_sources

        pruned_sources: List[Document] = []
        current_tokens = 0

        for source in file_sources:
            if current_tokens + source.tokens <= self.max_tokens:
                pruned_sources.append(source)
                current_tokens += source.tokens
            else:
                print(f"Token limit reached. Discarding remaining files starting from {source.file_path}.")
                break
        
        print(f"Pruning complete. Kept {len(pruned_sources)} files with {current_tokens} tokens.")
        return pruned_sources

class ExtractedSnippet(BaseModel):
    """
    Represents a text snippet extracted by the LLM, along with its relevance score.
    """
    score: int = Field(description="The relevance score of the snippet to the user's query, from 0 (not relevant) to 10 (highly relevant).")
    snippet: str = Field(description="The actual extracted text or code snippet.")

    # @field_validator('score')
    # @classmethod
    # def score_must_be_in_range(cls, v: int) -> int:
    #     """Ensures the score is within the valid range of 0-10."""
    #     if not 0 <= v <= 10:
    #         raise ValueError('score must be between 0 and 10')
    #     return v

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
        """''

        return {
            "conversations": conversations,
            "content_with_lines": content_with_lines
        }
      

    @llm.prompt()
    def _extract_content_prompt(self, conversations: List[Dict[str, str]], full_content: str) -> dict:
        """
        You are an expert content analyst. Your task is to extract the most relevant text snippets from a source document and score their relevance to a user's query.

        Here is the source document:
        <DOCUMENT>
        {{ full_content }}
        </DOCUMENT>

        Here is the conversation history. The last message is the user's primary request.
        <CONVERSATION_HISTORY>
        {% for msg in conversations %}
        <{{ msg.role }}>: {{ msg.content }}
        {% endfor %}
        </CONVERSATION_HISTORY>

        Your Task:
        1. Analyze the user's request in the conversation.
        2. Identify and extract the most relevant continuous blocks of text/code from the document.
        3. For each extracted snippet, assign a relevance score from 0 to 10, where 10 is most relevant and 0 is not relevant at all.
        4. Keep the snippets concise but complete. You can return up to 4 snippets.

        Output Requirements:
        - Your response MUST be a valid JSON array of objects.
        - Each object must have two keys: "score" (an integer from 0-10) and "snippet" (a string).
        - If no parts of the document are relevant, return an empty array [].
        - Do not include any text or explanations outside of the JSON array.

        Example output:
        ```json
        [
          {
            "score": 9,
            "snippet": "def calculate_pnl(trades, prices):\\n    # ... implementation ...\\n    return pnl"
          },
          {
            "score": 7,
            "snippet": "pnl_result = calculate_pnl(my_trades, daily_prices)"
          }
        ]
        ```
        """
        return {
            "conversations": conversations,
            "full_content": full_content
        }
    
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

    def _process_single_large_file(self, file_source: Document, conversations: List[Dict[str, Any]]) -> Document:
        """
        Processes a single large file to extract snippets. This is the target for our threads.
        Returns a new Document object with pruned content, or the original if it fails.
        """
        print(f"  - Starting snippet extraction for: {file_source.file_path}")
        try: 
        
            response_generator = self._extract_content_prompt(
                conversations=conversations,
                full_content=file_source.source_code
            )

            response_str = None
            try:
                while True:
                    next(response_generator)
            except StopIteration as e:
                response_str = e.value.content

            import re
            # 将所有非法反斜杠转义为合法形式，例如 \* -> \\*
            def escape_invalid_json_backslashes(s):
                return re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', s)

            clean_json_str = escape_invalid_json_backslashes(response_str)

            json_items = parse_json_string(clean_json_str)
            extracted_items = [ExtractedSnippet(**item) for item in json_items if isinstance(item, dict)]
            
            # --- 关键：过滤掉低分数的片段 ---
            # 我们可以设定一个阈值，比如只保留分数大于等于5的片段
            score_threshold = 5
            high_score_snippets = [item for item in extracted_items if item.score >= score_threshold]

            if not high_score_snippets:
                print(f"  - No snippets with score >= {score_threshold} found in {file_source.file_path}.")
                return Document(file_source.file_path, "")
            
            # (可选) 可以按分数从高到低排序，让最重要的内容出现在前面
            high_score_snippets.sort(key=lambda x: x.score, reverse=True)

            # --- 构建新的内容 ---
            new_content_parts = [
                f"# Highly relevant snippets from {file_source.file_path} (filtered by score >= {score_threshold}):\n"
            ]
            for item in high_score_snippets:
                # 在注释中包含分数，便于调试
                new_content_parts.append(f"\n# Relevance Score: {item.score}\n---\n{item.snippet}\n")
            
            new_content = "".join(new_content_parts)

            return Document(file_source.file_path, new_content)

        except Exception as e:
            print(f"  - Error extracting content from {file_source.file_path}: {e}")
            return Document(file_source.file_path, "")


    def prune(
        self, 
        file_sources: List[Document], 
        conversations: List[Dict[str, Any]]
    ) -> List[Document]:
        
        print(f"Applying concurrent 'extract' pruning strategy with {self.max_workers} workers...")
        
        # 1. 分组：小文件 vs 大文件
        small_files: List[Document] = []
        large_files: List[Document] = []

        try:
        
            current_tokens = 0
            for source in file_sources:
                if source is None: 
                    print("Warning: Encountered a None source in file_sources. Skipping.", file_sources)
                if current_tokens + source.tokens <= self.full_file_threshold:
                    small_files.append(source)
                    current_tokens += source.tokens
                else:
                    large_files.append(source)
        
        # print(f"Split files: {len(small_files)} small files (kept whole), {len(large_files)} large files (to be processed).")
        
       

            # 测试
            large_files += small_files  # 确保小文件也在后续处理列表中
            # 2. 并发处理大文件
            processed_large_files: List[Document] = []
            if large_files:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_source = {
                        executor.submit(self._process_single_large_file, source, conversations): source 
                        for source in large_files
                    }
                    
                    for future in as_completed(future_to_source):
                        try:
                            processed_source = future.result()
                            #if processed_source.tokens > 0: # 只保留有内容的
                            processed_large_files.append(processed_source)
                        except Exception as exc:
                            original_source = future_to_source[future]
                            print(f"Exception processing {original_source.file_path}: {exc}")

            # 3. 合并和最终剪枝
            # 将完整保留的小文件和处理后的大文件片段合并
            # 我们优先保留小文件，然后尝试添加处理后的大文件片段
            print("Merging results and performing final token check...")
            final_sources: List[Document] = []
            # final_tokens = self._count_total_tokens(small_files)
            # final_sources.extend(small_files)

            final_tokens = 0

            # 对处理后的大文件按（新）token数从小到大排序，优先添加小的
            processed_large_files.sort(key=lambda x: x.tokens)

            for source in processed_large_files:
                if final_tokens + source.tokens <= self.max_tokens:
                    final_sources.append(source)
                    final_tokens += count_tokens(source.source_code)
                    print(f"  - Added snippets from {source.file_path} ({source.tokens} tokens)")
                else:
                    print(f"  - Snippets from {source.file_path} ({source.tokens} tokens) too large to fit. Discarding.")
            
            print(f"Pruning complete. Final context has {len(final_sources)} files with {final_tokens} tokens.")
            return final_sources
        except Exception as e:
            import traceback    
            traceback.print_exc()
            print(f"Error during pruning: {e}. Returning original file sources.")


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