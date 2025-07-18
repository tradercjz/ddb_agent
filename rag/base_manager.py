# file: ddb_agent/rag/base_manager.py
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import threading
from typing import Any, List, Optional, Union

import pydantic

from rag.types import BaseIndexModel
from rag.types import CodeIndex, ProjectIndex
from .retrieval_result import RetrievalResult

class BaseIndexManager(ABC):
    """
    Abstract base class for all index managers (for code, text, etc.).
    """
    def __init__(self, project_path: str, index_file: str):
        self.project_path = project_path
        self.index_path = os.path.join(project_path, index_file)
        self.project_index: ProjectIndex = self._load_index()
        self._index_lock = threading.Lock()

    def get_all_indices(self) -> List[BaseIndexModel]:
        return self.project_index.files

    @abstractmethod
    def build_index(
        self, 
        file_extensions: Optional[Union[str, List[str]]] = None,
        max_workers: int = 4
    ):
        """
        Builds the index for a specific type of content.
        """
        pass

    # @abstractmethod
    # def retrieve(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
    #     """
    #     Retrieves the most relevant content for a given query.
    #     """
    #     pass

    from typing import List, Union

    def _add_or_update_and_save(self, new_item: Union[BaseIndexModel, List[BaseIndexModel]]):
        """
        A thread-safe template method to add/update an item or a list of items in the index and save.
        This method contains the algorithm skeleton.
        """
        with self._index_lock:
            # If new_item is a single BaseIndexModel, convert it to a list
            if isinstance(new_item, BaseIndexModel):
                new_item = [new_item]
            
            # Iterate over the list and update the index
            for item in new_item:
                self._update_internal_index(item)
            
            # Save the index
            self._save_index()

    @abstractmethod
    def _update_internal_index(self, new_item: BaseIndexModel):
        """
        (Abstract) Hook for subclasses to implement their specific index update logic.
        This method will be called within a thread-safe context.
        """
        pass

    def _load_index(self) -> ProjectIndex:
        if os.path.exists(self.index_path):
            try:
                return ProjectIndex.model_validate_json(open(self.index_path, 'r', encoding='utf-8').read())
            
            # 捕获 Pydantic 的 ValidationError
            except (json.JSONDecodeError, pydantic.ValidationError) as e:
                print(f"Warning: Could not load or validate index file. Starting fresh. Error: {e}")
                return ProjectIndex(files=[])
                
        # 如果文件不存在，返回一个空的 ProjectIndex
        return ProjectIndex(files=[])
    
    @abstractmethod
    def _process_single_file(self, file_path: str) -> Optional[BaseIndexModel]:
        """"""
        pass

    @abstractmethod
    def get_relevant_files(self, query: str, top_k: int = 5) -> List[str]:
        pass

    def _save_index(self):
        """Saves the current project index to the file."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)

        with open(self.index_path, 'w', encoding='utf-8') as f:
            f.write(self.project_index.model_dump_json(indent=2))
    
    def get_index_by_filepath(self, file_path: str) -> Optional[Any]:
        """
        Retrieves the CodeIndex object for a given file path.

        Args:
            file_path: The relative path of the file.

        Returns:
            The CodeIndex object if found, otherwise None.
        """
        # 为了提高查找效率，我们可以构建一个临时的字典映射
        # 如果频繁调用，可以将这个映射作为 DDBIndexManager 的一个属性
        index_map = {f.file_path: f for f in self.project_index.files}
        return index_map.get(file_path)

    def _discover_files(self, file_extensions: Optional[Union[str, List[str]]]) -> List[str]:
        """
        A common utility to discover files, shared by subclasses.
        """
        import os
        discovered_files = []
        ignore_dirs = {'.git', 'node_modules', 'dist', 'build', '__pycache__', '.idea', '.vscode', '.ddb_agent'}
        
        if file_extensions:
            if isinstance(file_extensions, str):
                extensions = [file_extensions]
            else:
                extensions = file_extensions
            extensions = [ext if ext.startswith('.') else '.' + ext for ext in extensions]
        else:
            extensions = None

        for root, dirs, files in os.walk(self.project_path, topdown=True):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for file in files:
                if extensions is None or any(file.endswith(ext) for ext in extensions):
                    full_path = os.path.join(root, file)
                    #relative_path = os.path.relpath(full_path, self.project_path)
                    discovered_files.append(full_path)
        
        return discovered_files
    
    def _calculate_md5(self, file_path: str) -> str:
        """Calculates the MD5 hash of a file."""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                # Read file in chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except FileNotFoundError:
            return "" # Return empty string if file not found

    
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
                        self._add_or_update_and_save(result_index)
                        print(f"[{processed_count}/{len(file_paths_to_index)}] Indexed and saved: {file_path}")
                    else:
                        print(f"[{processed_count}/{len(file_paths_to_index)}] Failed to index (skipped): {file_path}")
                except Exception as exc:
                    print(f"[{processed_count}/{len(file_paths_to_index)}] Exception for {file_path}: {exc}")
        
        
        print("Index building complete. All processed files have been saved incrementally.")
    