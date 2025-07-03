# file: ddb_agent/rag/rag_entry.py

import os

from context.pruner import SourceCode, get_pruner
from llm.llm_prompt import llm
from typing import List

from llm.models import ModelManager
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

    def _get_files_content(self, file_paths: List[str]) -> List[SourceCode]:
        """Reads file contents and creates SourceCode objects."""
        sources = []
        for file_path in file_paths:
            full_path = os.path.join(self.project_path, file_path)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 从索引中获取预先计算好的token数
                index_info = self.index_manager.get_index_by_filepath(file_path)
                tokens = index_info.tokens if index_info else -1 # 如果找不到索引，则让SourceCode自己计算
                sources.append(SourceCode(file_path, content, tokens))
            except Exception as e:
                print(f"Warning: Could not read file {file_path}: {e}")
        return sources

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
        
        current_sources = self._get_files_content(relevant_files)

        # 3. 迭代式剪枝循环
        pruning_attempts = 0
        max_pruning_attempts = 5 # 防止无限循环

        max_context_tokens = ModelManager.get_model_config('deepseek').max_context_tokens or 50000

        # 获取 pruner 实例
        # 我们在这里硬编码使用 'extract' 策略，因为这是需求
        pruner = get_pruner(
            strategy='extract',
            max_tokens = max_context_tokens
        )
        
        while pruning_attempts < max_pruning_attempts:
            pruning_attempts += 1
            print(f"\n--- Pruning Attempt #{pruning_attempts} ---")
            
            # 计算当前上下文总token
            total_tokens = sum(s.tokens for s in current_sources)
            print(f"Current context size: {total_tokens} tokens.")
            
            if total_tokens <= max_context_tokens:
                print("Context size is within limit. No more pruning needed.")
                break
            
            print(f"Context size ({total_tokens}) exceeds limit ({max_context_tokens}). Applying 'extract' pruner...")
            
            # 调用 pruner
            # todo:设计全局的conversation管理器
            current_sources = pruner.prune(current_sources, [])

            if not current_sources:
                print("Warning: Pruning resulted in an empty context.")
                break
        
        if sum(s.tokens for s in current_sources) > max_context_tokens:
            print(f"Warning: Could not prune context to fit within the limit after {max_pruning_attempts} attempts.")
            # 这里可以采取最终策略，比如只保留第一个文件
            current_sources = current_sources[:1]


        print("Step 3: Generating final answer with augmented context...")

        # 需要计算各个相关文件的大小

        # todo: 这里可能内容很多，需要进行裁剪
        # 裁剪方式1：多文件大模型并行裁剪
        # 2：暴力裁剪，直接截断
        
        # Step 5: Generate the final response
        response = self._chat_with_context(
            user_query=query,
            context_files=context_str
        )
        return response