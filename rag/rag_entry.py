# file: ddb_agent/rag/rag_entry.py

import os

from context.pruner import Document, get_pruner
from llm.llm_prompt import llm
from typing import List

from llm.models import ModelManager
from .code_index_manager import CodeIndexManager
from .text_index_manager import TextIndexManager

class DDBRAG:
    """
    A simple RAG implementation for DolphinDB agent.
    """
    def __init__(self, project_path: str, index_file: str = None):
        self.project_path = project_path
        self.index_file = index_file or os.path.join(project_path, ".ddb_agent", "file_index.json")
        self.index_manager = TextIndexManager(project_path=project_path, index_file = self.index_file)

    @llm.prompt()
    def _chat_prompt(self, user_query: str, context_files: str) -> str:
        """
        You are a world-class DolphinDB expert.
        Answer the user's query based on the provided file contexts.
        Be concise, accurate, and provide code examples where appropriate.

        Here are the relevant files and their content:
        <CONTEXT>
        {{ context_files }}
        </CONTEXT>

        User Query:
        {{ user_query }}

        Your Answer:
        """
        pass

    @llm.prompt()
    def _chat_without_context(self, user_query: str) -> str:

        """
        You are a world-class DolphinDB expert.
        Answer the user's query without any file context.
        Be concise, accurate, and provide code examples where appropriate.

        User Query:
        {{ user_query }}

        Your Answer:
        """
        pass

    @llm.prompt()
    def _chat_with_context(self, user_query: str, context_files: str) -> str:
        """
        You are a world-class DolphinDB expert.
        Answer the user's query based on the provided file contexts.
        Be concise, accurate, and provide code examples where appropriate.

        Here are the relevant files and their content:
        <CONTEXT>
        {{ context_files }}
        </CONTEXT>

        User Query:
        {{ user_query }}

        Your Answer:
        """
        pass

    def _get_files_content(self, file_paths: List[str]) -> List[Document]:
        """Reads file contents and creates Document objects."""
        sources = []
        for file_path in file_paths:
            full_path = os.path.join(self.project_path, file_path)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 从索引中获取预先计算好的token数
                index_info = self.index_manager.get_index_by_filepath(file_path)
                tokens = index_info.tokens if index_info else -1 # 如果找不到索引，则让Document自己计算
                sources.append(Document(file_path, content, tokens))
            except Exception as e:
                print(f"Warning: Could not read file {file_path}: {e}")
        return sources

    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        """
        Retrieves the most relevant source code files for a given query.

        Args:
            query: The user's query string.
            top_k: The maximum number of relevant files to return.

        Returns:
            A list of Document objects containing the content of the relevant files.
        """
        print("Step 1: Retrieving relevant file paths...")
        relevant_file_paths = self.index_manager.get_relevant_files(query, top_k=top_k)
        
        if not relevant_file_paths:
            print("No relevant files found in the index.")
            return []

        print(f"Step 2: Found {len(relevant_file_paths)} relevant files: {', '.join(relevant_file_paths)}")

        # Step 3: Read file contents and return as Document objects
        return self._get_files_content(relevant_file_paths)