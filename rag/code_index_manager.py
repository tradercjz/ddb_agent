# file: ddb_agent/rag/index_manager.py (重构后)

import os
import json
import pydantic
from typing import List, Dict, Optional, Union
from token_counter import count_tokens

from utils.json_parser import parse_json_string # 引入 token 计数器
from .types import CodeIndex, ProjectIndex, Symbol
from llm.llm_prompt import llm

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base_manager import BaseIndexManager

class CodeIndexManager(BaseIndexManager):
    """
    Manages the creation, loading, and querying of the project index for DolphinDB.
    Handles large files by splitting them into chunks and using a map-reduce approach.
    """
    # 为每个块设置一个合理的 token 上限，留出余量给 prompt
    MAX_TOKENS_PER_CHUNK = 60*1000

    def __init__(self, project_path: str, index_file: str = ".ddb_agent/index.json"):
        super().__init__(project_path, index_file)


    def _save_index(self):
        """Saves the code project index to disk."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, 'w', encoding='utf-8') as f:
            f.write(self.project_index.model_dump_json(indent=2))

    def _update_internal_index(self, new_item: CodeIndex):
        """Updates the in-memory ProjectIndex with a new CodeIndex."""
        if not isinstance(new_item, CodeIndex):
            print(f"Warning: CodeIndexManager received an item of wrong type: {type(new_item)}")
            return
            
        found = False
        for i, existing_file in enumerate(self.project_index.files):
            if existing_file.file_path == new_item.file_path:
                self.project_index.files[i] = new_item
                found = True
                break
        if not found:
            self.project_index.files.append(new_item)

    # _process_single_file, _discover_files 和所有 @llm.prompt 方法保持不变
    def _process_single_file(self, file_path: str) -> Optional[CodeIndex]:
        # ... (原有实现不变) ...
        full_path = os.path.join(self.project_path, file_path)
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            total_tokens = count_tokens(content)
            final_file_index = None

            if total_tokens <= self.MAX_TOKENS_PER_CHUNK:
                response_str = self._create_file_index_prompt_for_small_file(
                    file_path=file_path, file_content=content
                )
                json_content = parse_json_string(response_str)
                json_content["tokens"] = total_tokens
                final_file_index = CodeIndex(**json_content)
            else:
                chunks = self._split_code_into_chunks(content)
                
                chunk_summaries, all_symbols = [], []
                for i, chunk in enumerate(chunks):
                    response_str = self._summarize_chunk_prompt(
                        file_path=file_path, code_chunk=chunk
                    )
                    json_content = parse_json_string(response_str)
                    chunk_result = json.loads(json_content)
                    chunk_summaries.append(chunk_result["file_summary"])
                    all_symbols.extend([Symbol(**s) for s in chunk_result["symbols"]])

                summaries_str = "\n".join(f"- {s}" for s in chunk_summaries)
                response_str = self._reduce_summaries_prompt(
                    file_path=file_path, chunk_summaries=summaries_str
                )
                json_content = parse_json_string(response_str)
                final_summary = json.loads(json_content)["final_summary"]

                final_file_index = CodeIndex(
                    file_path=file_path,
                    file_summary=final_summary,
                    symbols=all_symbols,
                    is_aggregated=True,
                    chunk_count=len(chunks),
                    tokens = total_tokens
                )

            return final_file_index

        except Exception as e:
            print(f"Error processing file {file_path}: {e}")
            return None

    # 新增：代码切分辅助函数
    def _split_code_into_chunks(self, code: str) -> List[str]:
        """
        Splits code into chunks that are smaller than MAX_TOKENS_PER_CHUNK,
        trying to split at logical boundaries (e.g., function definitions).
        """
        chunks = []
        current_chunk_lines = []
        lines = code.splitlines(keepends=True)
        
        for line in lines:
            current_chunk_lines.append(line)
            # 简单地通过行数或token数来切分，更复杂的可以基于AST
            # 这里我们使用token计数，并在达到阈值时切分
            current_content = "".join(current_chunk_lines)
            if count_tokens(current_content) > self.MAX_TOKENS_PER_CHUNK:
                # 当超出时，我们将当前块（除了最后一行）作为一个chunk
                chunk_to_add = "".join(current_chunk_lines[:-1])
                if chunk_to_add: # 避免添加空块
                   chunks.append(chunk_to_add)
                # 新的块从最后一行开始
                current_chunk_lines = [line]

        # 添加最后一个剩余的块
        if current_chunk_lines:
            chunks.append("".join(current_chunk_lines))
        
        return chunks

    @llm.prompt()
    def _summarize_chunk_prompt(self, file_path: str, code_chunk: str) -> str:
        """
        You are an expert DolphinDB code analyst.
        The following code is a CHUNK from a larger file: {{ file_path }}.

        Code Chunk:
        ```dolphiindb
        {{ code_chunk }}
        ```

        Please provide a concise summary of THIS CHUNK's main purpose and functionality.
        Also, list all key symbols (functions, modules, etc.) defined in THIS CHUNK.

        Your response MUST be in the following JSON format.
        ```json
        {
          "file_summary": "A brief summary of this specific code chunk.",
          "symbols": [
            {"name": "symbol_name", "type": "function"}
          ]
        }
        ```
        """
        pass

    @llm.prompt()
    def _reduce_summaries_prompt(self, file_path: str, chunk_summaries: str) -> str:
        """
        You are an expert DolphinDB code analyst.
        I have analyzed a large file, '{{ file_path }}', by splitting it into several chunks.
        Here are the summaries for each chunk:

        <CHUNK_SUMMARIES>
        {{ chunk_summaries }}
        </CHUNK_SUMMARIES>

        Your task is to synthesize these individual chunk summaries into a single, cohesive, high-level summary for the entire file.
        The final summary should describe the overall purpose and functionality of '{{ file_path }}'.

        Your response should be a single JSON string with one key "final_summary".
        Example:
        ```json
        {
            "final_summary": "A comprehensive summary of the entire file."
        }
        ```
        """
        pass
    
    # 原有的_create_file_index_prompt保持不变，但我们可以称之为处理小文件的方法
    @llm.prompt()
    def _create_file_index_prompt_for_small_file(self, file_path: str, file_content: str) -> str:
        # ... (和上一版中的 _create_file_index_prompt 完全相同) ...
        """
        You are an expert DolphinDB code analyst.
        Your task is to analyze the following DolphinDB script file and extract its metadata.

        File Path: {{ file_path }}

        File Content:
        ```dolphiindb
        {{ file_content }}
        ```

        Please provide a concise summary of this file's main purpose and functionality.
        Also, list all key symbols defined in this script, including functions, modules, and any important global variables.

        Your response MUST be in the following JSON format. Do not add any extra text or explanations.
        ```json
        {
          "file_path": "{{ file_path }}",
          "file_summary": "A brief, one-sentence summary of the file's purpose.",
          "symbols": [
            {"name": "symbol_name_1", "type": "function"},
            {"name": "symbol_name_2", "type": "module"},
            ...
          ]
        }
        ```
        """
        pass

    # get_relevant_files 方法保持不变
    @llm.prompt()
    def _get_relevant_files_prompt(self, user_query: str, index_content: str) -> str:
        # ... (和上一版中的 _get_relevant_files_prompt 完全相同) ...
        """
        You are a smart file retrieval assistant for a DolphinDB project.
        Based on the user's query, your task is to identify the most relevant files from the project index.

        User Query:
        {{ user_query }}

        Project Index (contains a list of all files with their summaries and defined symbols):
        ```json
        {{ index_content }}
        ```

        Analyze the project index and determine which files are most relevant to answering the user's query.
        Consider file summaries and the symbols they contain.

        Your response MUST be a JSON list of strings, containing only the file paths of the relevant files.
        Example:
        ```json
        [
            "path/to/relevant_file1.dos",
            "path/to/relevant_file2.dos"
        ]
        ```
        Return an empty list if no files seem relevant. Do not add any other text.
        """
        pass

    def get_relevant_files(self, query: str, top_k: int = 5) -> List[str]:
        """
        Uses LLM to find the most relevant files for a given query based on the index.
        """
        if not self.project_index.files:
            return []

        index_json_str = self.project_index.model_dump_json()

        response_str = self._get_relevant_files_prompt(
            user_query=query,
            index_content=index_json_str
        )
        
        try:
            relevant_files = parse_json_string(response_str)
            print("relevant_files:", relevant_files)
            # You might want to respect top_k here if the LLM returns too many files
            return relevant_files[:top_k]
        except (json.JSONDecodeError, IndexError) as e:
            print(f"Error parsing LLM response for relevant files: {e}")
            return []