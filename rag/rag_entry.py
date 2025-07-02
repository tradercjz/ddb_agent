# file: ddb_agent/rag/rag_entry.py

import os

from llm.llm_prompt import llm
from typing import List
from .index_manager import DDBIndexManager

class DDBRAG:
    """
    A simple RAG implementation for DolphinDB agent.
    """
    def __init__(self, project_path: str, index_file: str = None):
        self.project_path = project_path
        self.index_file = index_file or os.path.join(project_path, ".ddb_agent", "index.json")
        self.index_manager = DDBIndexManager( project_path=project_path, index_file = index_file)

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


    def chat(self, query: str):
        """
        Handles a user query using the RAG pipeline.
        """
        print("Step 1: Retrieving relevant files...")
        relevant_files = self.index_manager.get_relevant_files(query)
        
        if not relevant_files:
            print("No relevant files found in the index. Answering based on general knowledge.")
            # Fallback: answer without context
            return self._chat_without_context(query)

        print(f"Step 2: Found {len(relevant_files)} relevant files: {', '.join(relevant_files)}")

        # Step 3: Augment the context by reading file contents
        context_str = ""
        for file_path in relevant_files:
            full_path = os.path.join(self.project_path, file_path)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                context_str += f"--- File: {file_path} ---\n{content}\n\n"
            except Exception as e:
                print(f"Warning: Could not read file {file_path}: {e}")
        
        print("Step 3: Generating final answer with augmented context...")

        # todo: 这里可能内容很多，需要进行裁剪
        # 裁剪方式1：多文件大模型并行裁剪
        # 2：暴力裁剪，直接截断
        
        # Step 5: Generate the final response
        response = self._chat_with_context(
            user_query=query,
            context_files=context_str
        )
        return response