# file: ddb_agent/rag/candidate_selector.py

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from typing import Generator, List, Dict, Any
import re
from llm.llm_client import StreamChunk
from rag.base_manager import BaseIndexManager
from rag.rag_status import AnyRagStatus, RagError, RagSelectionEnd, RagSelectionProgress
from rag.types import BaseIndexModel
from token_counter import count_tokens
from utils.json_parser import parse_json_string
from utils.tokenizer import smart_tokenize 
from llm.llm_prompt import llm


class CandidateSelector:
    """
    Selects a subset of candidate index items based on simple, fast matching algorithms.
    """
    def __init__(self, all_index_items: List[Dict[str, Any]], index_manager: BaseIndexManager):
        """
        Args:
            all_index_items: A list of all index items (dicts, not Pydantic models for speed).
        """
        self.all_items = all_index_items
        self.index_manager = index_manager

    def select_by_keyword(self, query: str, top_n: int = 50) -> List[Dict[str, Any]]:
        """
        Selects candidates by scoring them based on keyword matches in their metadata.
        """
        query_keywords = smart_tokenize(query)

        print("query_keywords:",query_keywords)

        if not query_keywords:
            return []

        scored_items = []
        for item in self.all_items:
            score = 0
            
            # 1. 检查文件名
            item_name = item.file_path
            for keyword in query_keywords:
                if keyword in item_name.lower():
                    score += 5 # 文件名匹配权重更高

            # 2. 检查摘要
            summary = item.summary
            summary_lower = summary.lower()
            for keyword in query_keywords:
                if keyword in summary_lower:
                    score += 2
            
            # 3. 检查符号
            searchable_terms =  item.keywords
            searchable_terms_lower = {term.lower() for term in searchable_terms}

            for keyword in query_keywords:
                if keyword in searchable_terms_lower:
                    score += 3 # 符号/关键词匹配权重较高
            
            if score > 0:
                scored_items.append({'item': item, 'score': score})
        
        # 按分数排序并返回 top_n
        scored_items.sort(key=lambda x: x['score'], reverse=True)
        
        return [scored['item'] for scored in scored_items[:top_n]]
    

class LLMCandidateSelector:
    """
    Selects candidates by using an LLM to screen chunks of the index in parallel.
    """
    # 每个发给LLM的块，其token上限
    MAX_TOKENS_PER_CHUNK = 128000 # 假设使用一个大的窗口模型进行筛选

    def __init__(self, all_index_items: List[BaseIndexModel],  index_manager: BaseIndexManager):
        self.all_items = all_index_items
        self.index_manager = index_manager

    # 指定使用chat模型快一些
    @llm.prompt()
    def _select_from_chunk_prompt(self, user_query: str, index_chunk_json: str) -> str:
        """
        You are an expert retrieval assistant. Your task is to analyze a CHUNK of a project's index, 
        identify items relevant to the user's query, and assign a relevance score.

        User Query:
        {{ user_query }}

        Index Chunk (a subset of the project's total index):
        <INDEX_CHUNK>
        {{ index_chunk_json }}
        </INDEX_CHUNK>

        Instructions:
        1.  Review each item in the index chunk.
        2.  Compare the user's query against each item's metadata.
        3.  For each relevant item, assign a relevance score from 1 (least relevant) to 10 (most relevant).
        4.  If an item is not relevant, do not include it in the output.

        Your response MUST be a JSON array of objects. Each object must contain "file_path" and "score".
        If no items in this chunk are relevant, return an empty list [].
        Do not add any other text or explanations.

        Example Response:
        ```json
        [
            { "file_path": "path/to/code_file.dos", "score": 9 },
            { "file_path": "document.md-chunk_5", "score": 7 }
        ]
        ```
        """
   

    def _split_index_into_chunks(self) -> List[List[Dict]]:
        """Splits the list of all index items into manageable chunks."""
        chunks = []
        current_chunk = []
        current_tokens = 0

        for item in self.all_items:
            # 将Pydantic对象转为字典
            item_dict = {
                "file_path": item.file_path,
                "summary": item.summary,
                "keywords": item.keywords
            }   
            item_str = json.dumps(item_dict, ensure_ascii=False)
            item_tokens = count_tokens(item_str)

            if current_tokens + item_tokens > self.MAX_TOKENS_PER_CHUNK and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = 0
            
            current_chunk.append(item_dict)
            current_tokens += item_tokens
        
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def _select_candidates_from_chunk(self, query: str, index_chunk: List[Dict]) -> List[Dict]:
        """The target function for each thread, processing one chunk."""
        try:
            chunk_json_str = json.dumps(index_chunk, indent=2, ensure_ascii=False)

            prompt_generator = self._select_from_chunk_prompt(
                user_query=query,
                index_chunk_json=chunk_json_str
            )

            # RAG阶段，忽略筛选相关的LLM请求处理的中间过程
            try:
                while True:
                    chunk = next(prompt_generator)
                    pass 
            except StopIteration as e:
                response_str = e.value

            # 解析LLM返回的JSON列表
            relevant_items_in_chunk = parse_json_string(response_str.content)
            return relevant_items_in_chunk  if isinstance(relevant_items_in_chunk, list) else []
        except Exception as e:
            print(f"Error processing an index chunk with LLM: {e}")
            return []

    def select(self, query: str, max_workers: int = 4) -> Generator[AnyRagStatus, None, List[BaseIndexModel]]:
        """
        Performs the parallel selection process.
        """
        # 1. 分块
        index_chunks = self._split_index_into_chunks()
        if not index_chunks:
            return []
        
        yield RagSelectionProgress(
            message=f"Phase 1: Split index into {len(index_chunks)} chunks for parallel filter.",
            processed_count=0,
            total_count=len(index_chunks),
            found_count=0
        )
        # 2. 并行筛选
        all_candidates_with_scores = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            processed_chunks = 0
            future_to_chunk_index = {
                executor.submit(self._select_candidates_from_chunk, query, chunk): i
                for i, chunk in enumerate(index_chunks)
            }
            
            total_count = len(index_chunks)
            for future in as_completed(future_to_chunk_index):
                chunk_index = future_to_chunk_index[future]
                try:
                    result = future.result()
                    processed_chunks += 1
                    if result:
                        all_candidates_with_scores.extend(result)
                        yield RagSelectionProgress(
                            message=f"Phase 1: filter index  {processed_chunks}/{total_count} chunks...",
                            processed_count=processed_chunks,
                            total_count=total_count,
                            found_count=len(result)
                        )
                except Exception as exc:
                    yield RagError(
                        message=f"Chunk {chunk_index + 1} processing failed.",
                        step="selection",
                        error_details=str(exc)
                    )

        best_candidates = {}
        for cand in all_candidates_with_scores:
            path = cand.get("file_path")
            score = cand.get("score", 0)
            if path:
                if path not in best_candidates or score > best_candidates[path].get("score", 0):
                    best_candidates[path] = cand
        
        # 3. 排序：根据分数从高到低排序
        sorted_candidates_list = sorted(best_candidates.values(), key=lambda x: x.get("score", 0), reverse=True)

        # 4. 转换：将排序后的字典列表转换回 BaseIndexModel 对象列表
        final_candidates = []
        for item_dict in sorted_candidates_list:
            # get_index_by_filepath 依然可以复用
            index_item = self.index_manager.get_index_by_filepath(item_dict["file_path"])
            if index_item:
                final_candidates.append(index_item)

        yield RagSelectionEnd(
            message=f"Phase 1: Found and ranked {len(final_candidates)} unique candidates.",
            candidate_count=len(final_candidates)
        )
        return final_candidates
