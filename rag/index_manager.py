# file: ddb_agent/rag/index_manager.py (重构后)

import os
import json
import pydantic
from typing import List, Dict, Optional, Union
from token_counter import count_tokens

from utils.json_parser import parse_json_string # 引入 token 计数器
from .types import FileIndex, ProjectIndex, Symbol
from llm.llm_prompt import llm

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class DDBIndexManager:
    """
    Manages the creation, loading, and querying of the project index for DolphinDB.
    Handles large files by splitting them into chunks and using a map-reduce approach.
    """
    # 为每个块设置一个合理的 token 上限，留出余量给 prompt
    MAX_TOKENS_PER_CHUNK = 60*1000

    def __init__(self, project_path: str, index_file: str = ".ddb_agent/index.json"):

        self.project_path = project_path
        self.index_path = os.path.join(project_path, index_file)
        self.project_index: ProjectIndex = self._load_index()
        self._index_lock = threading.Lock() 

    # _load_index 和 _save_index 方法保持不变...
    def _load_index(self) -> ProjectIndex:
        """Loads the project index from the file, or returns an empty one if not found."""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return ProjectIndex(**data)
            except (json.JSONDecodeError, pydantic.ValidationError) as e:
                print(f"Warning: Could not load or validate index file. Starting fresh. Error: {e}")
                return ProjectIndex(files=[])
        return ProjectIndex(files=[])

    def _save_index(self):
        """Saves the current project index to the file."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)

        with open(self.index_path, 'w', encoding='utf-8') as f:
            f.write(self.project_index.model_dump_json(indent=2))

    def _update_and_save_single_index(self, file_index: FileIndex):
        """
        Thread-safely updates the main project index with a single new FileIndex
        and saves the entire index to disk.
        """
        # 使用 with 语句确保锁会被正确获取和释放
        with self._index_lock:
            # 更新 project_index
            found = False
            for i, existing_file in enumerate(self.project_index.files):
                if existing_file.module_name == file_index.module_name:
                    self.project_index.files[i] = file_index
                    found = True
                    break
            if not found:
                self.project_index.files.append(file_index)
            
            # 保存到文件
            self._save_index()

    # _process_single_file, _discover_files 和所有 @llm.prompt 方法保持不变
    def _process_single_file(self, file_path: str) -> Optional[FileIndex]:
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
                final_file_index = FileIndex(**json_content)
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

                final_file_index = FileIndex(
                    module_name=file_path,
                    file_summary=final_summary,
                    symbols=all_symbols,
                    is_aggregated=True,
                    chunk_count=len(chunks)
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
          "module_name": "{{ file_path }}",
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

    # 文件发现辅助函数
    def _discover_files(self, file_extensions: Optional[Union[str, List[str]]]) -> List[str]:
        """
        Recursively discovers files in the project path with given extensions.
        Ignores common unnecessary directories.
        """
        discovered_files = []
        # 常见的需要忽略的目录
        ignore_dirs = {'.git', 'node_modules', 'dist', 'build', '__pycache__', '.idea', '.vscode', '.ddb_agent'}
        
        # 统一处理文件后缀
        if file_extensions:
            if isinstance(file_extensions, str):
                extensions = [file_extensions]
            else:
                extensions = file_extensions
            # 确保所有后缀都以'.'开头
            extensions = [ext if ext.startswith('.') else '.' + ext for ext in extensions]
        else:
            extensions = None # 如果为None，则匹配所有文件

        for root, dirs, files in os.walk(self.project_path, topdown=True):
            # 从dirs列表中原地移除需要忽略的目录，以避免walk进入这些目录
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for file in files:
                # 根据后缀过滤文件
                if extensions is None or any(file.endswith(ext) for ext in extensions):
                    full_path = os.path.join(root, file)
                    # 获取相对于项目根目录的路径
                    relative_path = os.path.relpath(full_path, self.project_path)
                    discovered_files.append(relative_path)
        
        return discovered_files

    # 重构后的 build_index 方法
    def build_index(self, file_extensions: Optional[Union[str, List[str]]] = None, max_workers: int = 4):
        """
        Automatically discovers files and builds or updates the index.

        Args:
            file_extensions: A list of file extensions to include (e.g., ['.dos', '.txt']).
                             If None, all files will be processed.
        """
        # 1. 自动发现文件
        print(f"Discovering files with extensions: {file_extensions or 'All'} in '{self.project_path}'...")
        file_paths_to_index = self._discover_files(file_extensions)

        if not file_paths_to_index:
            print("No matching files found to index.")
            return
    

        print(f"Found {len(file_paths_to_index)} files to build index...")

        # 2. 使用 ThreadPoolExecutor 并发处理文件
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_filepath = {executor.submit(self._process_single_file, fp): fp for fp in file_paths_to_index}
            
            processed_count = 0
            for future in as_completed(future_to_filepath):
                file_path = future_to_filepath[future]
                processed_count += 1
                try:
                    # 获取单个文件的处理结果
                    result_index = future.result()
                    
                    if result_index:
                        # --- 核心修改在这里 ---
                        # 调用线程安全的更新和保存方法
                        self._update_and_save_single_index(result_index)
                        print(f"[{processed_count}/{len(file_paths_to_index)}] Indexed and saved: {file_path}")
                    else:
                        print(f"[{processed_count}/{len(file_paths_to_index)}] Failed to index (skipped): {file_path}")
                except Exception as exc:
                    print(f"[{processed_count}/{len(file_paths_to_index)}] Exception for {file_path}: {exc}")
        
        
        print("Index building complete. All processed files have been saved incrementally.")
    
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