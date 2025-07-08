# file: ddb_agent/rag/rag_entry.py

import json
import os

from context.pruner import Document, get_pruner
from llm.llm_prompt import llm
from typing import Dict, List

from llm.models import ModelManager
from rag.types import BaseIndexModel
from utils.json_parser import parse_json_string
from .code_index_manager import CodeIndexManager
from .text_index_manager import TextIndexManager
from .candidate_selector import CandidateSelector, LLMCandidateSelector 

class DDBRAG:
    """
    A simple RAG implementation for DolphinDB agent.
    """
    def __init__(self, project_path: str, index_file: str = None, selection_strategy: str = 'llm' ):
        """ 
            selection_strategy: 处理索引过大场景
        """
        self.project_path = project_path
        self.index_file = index_file or os.path.join(project_path, ".ddb_agent", "file_index.json")
        self.index_manager = TextIndexManager(project_path=project_path, index_file = self.index_file)
        self.selection_strategy = selection_strategy

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

    @llm.prompt()
    def _rerank_candidates_prompt(self, user_query: str, candidates_json: str) -> str:
        """
        You are an expert re-ranking system. Your task is to analyze a list of candidate documents
        and select the most relevant ones for the given user query.

        User Query:
        {{ user_query }}

        Candidate Documents (metadata only):
        <CANDIDATES>
        {{ candidates_json }}
        </CANDIDATES>

        Please review the candidates and return a JSON list of the file paths (`module_name` or `source_document`) 
        or chunk IDs (`chunk_id`) of the TOP 5 most relevant items. Order them from most to least relevant.

        Your response MUST be a valid JSON list of strings.
        Example:
        ```json
        [
            "path/to/code_file.dos",
            "document.md-chunk_5",
            "utils/another_file.dos"
        ]
        ```
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
        Retrieves the most relevant documents using a two-step process.
        """
        print("--- Starting Two-Step Retrieval ---")
        
        # 1. 从所有索引源获取全部索引数据
        all_text_indices = self.index_manager.get_all_indices()
        all_indices = all_text_indices

        if not all_indices:
            print("No indices found to search from.")
            return []

        # 2. 阶段一：粗筛 (Candidate Selection)
        candidates: List[BaseIndexModel]
        if self.selection_strategy == 'llm':
            selector = LLMCandidateSelector(all_indices, self.index_manager)
            candidates = selector.select(query, max_workers=10) # 并发LLM筛选
        elif self.selection_strategy == 'keyword':
            selector = CandidateSelector(all_indices)
            candidates = selector.select_by_keyword(query, top_n=50) # 关键词筛选
        else:
            raise ValueError(f"Unknown selection strategy: {self.selection_strategy}")

        if not candidates:
            print("No relevant candidates found after initial selection.")
            return []
        
        print(f"Found {len(candidates)} candidates. Proceeding to Phase 2...")

        # 3. 阶段二：精排 (Re-ranking by LLM)
        print("Phase 2: Re-ranking candidates with LLM...")
        #  先用列表推导式和 .model_dump() 将 Pydantic 对象列表转换为字典列表
        print("candidates:", candidates)
        candidates_for_llm = [c.model_dump() for c in candidates if c is not None]
        #  然后再对这个字典列表进行 JSON 序列化
        candidates_json_str = json.dumps(candidates_for_llm, indent=2, ensure_ascii=False)

        print("candidates_json_str:", candidates_json_str)
        
        response_str = self._rerank_candidates_prompt(
            user_query=query,
            candidates_json=candidates_json_str
        )
        
        try:
            # LLM 返回最终的、排序好的标识符列表
            final_identifiers = parse_json_string(response_str)
        except Exception as e:
            print(f"Error parsing LLM re-ranking response: {e}. Falling back to top candidates from selection.")
            # 后备方案：如果LLM精排失败，直接使用粗筛结果
            final_identifiers = [
                c.get('module_name') or c.get('chunk_id') for c in candidates
            ]

        print(f"LLM selected and re-ranked {len(final_identifiers)} items.")

        # 4. 根据最终的标识符列表，获取并返回文件/文本块内容
        return self._get_files_content(final_identifiers)
       