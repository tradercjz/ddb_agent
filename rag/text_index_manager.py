# file: ddb_agent/rag/text_index_manager.py

import os
import json
from typing import List, Tuple
from llm.llm_prompt import llm
from token_counter import count_tokens
from utils.json_parser import parse_json_string
from .types import TextChunkIndex
from utils.text_extractor import extract_text_from_file
from .base_manager import BaseIndexManager
from llm.models import ModelManager

class TextIndexManager(BaseIndexManager):
    """Manages indexing and retrieval for text documents."""

    MAX_TOKENS_PER_CHUNK = 100*1000

    def __init__(self, project_path: str, index_file: str = ".ddb_agent/text_index"):
        super().__init__(project_path, index_file)

    @llm.prompt(model="deepseek-chat")
    def _create_index_for_small_file(self, file_path: str, file_content: str):
        """
        你是一位专业的文档分析专家。你的任务是处DolphinDB文档，并为其提取用于搜索引擎的关键元数据。

        源文档 (Source Document): {{ source_document }}
        分块位置 (Chunk Location): Lines {{ start_line }} to {{ end_line }}
        
        文本分块内容 (Text Chunk Content):
        <CONTENT>
        {{ content }}
        </CONTENT>

        请执行以下操作：
        1.  **总结 (Summarize)**：用一个简洁的句子概括这个文本片段的核心要点。
        2.  **关键词 (Keywords)**：提取3-5个相关的关键词。
        3.  **虚拟问题 (Hypothetical Question)**：构思一个清晰、单一的问题，这个文本片段可以直接回答该问题。这个问题将用于搜索。

        你的回答**必须**遵循以下 JSON 格式。不要添加任何额外的文字或解释。
        ```json
        {
          "file_path": "{{ file_path }}",
          "chunk_id": "0"
          "source_document": "{{ source_document }}",
          "start_line": {{ start_line }},
          "end_line": {{ end_line }},
          "summary": "对文本片段内容的简洁摘要。",
          "keywords": ["关键词1", "关键词2", "关键词3"],
          "hypothetical_question": "一个该文本片段可以回答的问题。"
        }
        ```
        """
        return {
            "file_path": file_path,
            "chunk_id": "0",
            "source_document": file_path,
            "start_line": 1,
            "end_line": len(file_content.splitlines()),
            "content": file_content.replace('"', '\\"'),  # Escape double quotes for JSON
        }


        
    @llm.prompt()
    def _create_chunk_index_prompt(
        self, 
        file_path: str,
        chunk_id: str,
        source_document: str,
        start_line: int,
        end_line: int,
        content: str
    ) -> dict:
        """
        You are an expert document analyst. Your task is to process a chunk of text from a larger document 
        and extract key metadata for a search index.

        Source Document: {{ source_document }}
        Chunk Location: Lines {{ start_line }} to {{ end_line }}
        
        Text Chunk Content:
        <CONTENT>
        {{ content }}
        </CONTENT>

        Please perform the following actions:
        1.  **Summarize**: Write a concise, one-sentence summary of this chunk's main point.
        2.  **Keywords**: Extract 3-5 relevant keywords.
        3.  **Hypothetical Question**: Formulate a single, clear question that this chunk of text could directly answer. This question will be used for searching.

        Your response MUST be in the following JSON format. Do not add any extra text or explanations.
        ```json
        {
          "file_path": "{{ file_path }}",
          "chunk_id": "{{ chunk_id }}",
          "source_document": "{{ source_document }}",
          "start_line": {{ start_line }},
          "end_line": {{ end_line }},
          "summary": "A concise summary of the chunk's content.",
          "keywords": ["keyword1", "keyword2", "keyword3"],
          "hypothetical_question": "A question that this chunk can answer."
        }
        ```
        """
        # 使用 `e`过滤器来转义JSON字符串中的特殊字符
        return {"content": content.replace('"', '\\"')}

    # --- 文本分块与索引构建 ---

    def _chunk_text(self, text: str, chunk_size: int = MAX_TOKENS_PER_CHUNK, overlap: int = 128) -> List[Tuple[int, int, str]]:
        """
        Splits text into chunks based on line count, with overlap.
        Returns a list of (start_line, end_line, content) tuples.
        """
        lines = text.splitlines()
        chunks = []
        start_index = 0
        

        # 1 English character ≈ 0.3 token.
        # 1 Chinese character ≈ 0.6 token.
        while start_index < len(lines):
            end_index = min(start_index + chunk_size, len(lines))
            chunk_lines = lines[start_index:end_index]
            
            # Line numbers are 1-based
            chunks.append((start_index + 1, end_index, "\n".join(chunk_lines)))
            
            start_index += (chunk_size - overlap)
            if start_index >= end_index: # Ensure progress
                start_index = end_index

        return chunks
    
    
    def _save_index(self):
        """Saves the code project index to disk."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, 'w', encoding='utf-8') as f:
            #f.write(self.project_index.model_dump_json(indent=2))
            json.dump(self.project_index.model_dump(), f, indent=2, ensure_ascii=False)

    def _update_internal_index(self, new_item: TextChunkIndex):
        """Updates the in-memory ProjectIndex with a new CodeIndex."""
        if not isinstance(new_item, TextChunkIndex):
            print(f"Warning: TextIndexManager received an item of wrong type: {type(new_item)}")
            return
            
        found = False
        for i, existing_file in enumerate(self.project_index.files):
            if existing_file.file_path == new_item.file_path:
                self.project_index.files[i] = new_item
                found = True
                break
        if not found:
            self.project_index.files.append(new_item)


    def _process_single_file(self, file_path: str):
        """
        Extracts text from a file, chunks it, and creates an index for each chunk.
        """
        print(f"Starting to index file: {file_path}")

        index_info = self.get_index_by_filepath(file_path)
        if index_info:
            print(f"  - File {file_path} is already indexed. Skipping.")
            return None
        
        try:
            # 1. 从文件提取纯文本
            full_text = extract_text_from_file(file_path)
            if not full_text:
                print(f"  - No text could be extracted from {file_path}. Skipping.")
                return
        except Exception as e:
            print(f"  - Error extracting text from {file_path}: {e}")
            return
        

        try:
            total_tokens = count_tokens(full_text)

            chunks = []
            final_chunk_index = []
            if total_tokens <= self.MAX_TOKENS_PER_CHUNK:
                response_generator = self._create_index_for_small_file(
                    file_path=file_path,
                    file_content=full_text
                )
                
                try:
                    while True:
                        part = next(response_generator)
                        pass
                except StopIteration as e:
                    response_str = e.value 

                json_content = parse_json_string(response_str.content)
                final_chunk_index = [TextChunkIndex(**json_content)]
            else:
                chunks = self._chunk_text(full_text)

                # 3. 为每个块创建索引 (可以并发处理)
                for i, (start_line, end_line, content) in enumerate(chunks):
                    chunk_id = f"{os.path.basename(file_path)}-chunk_{i}"
                    print(f"    - Indexing chunk {i+1}/{len(chunks)} (lines {start_line}-{end_line})...")
                    
                    try:
                        # 调用 LLM 生成索引元数据
                        response_str = self._create_chunk_index_prompt(
                            file_path=file_path,
                            chunk_id=chunk_id,
                            source_document=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            content=content
                        )

                        json_content = parse_json_string(response_str)
                        chunk_index = TextChunkIndex(**json_content)
                        
                        final_chunk_index.append(chunk_index)
                    except Exception as e:
                        print(f"    - Error indexing chunk {i+1}: {e}")
                

            self._add_or_update_and_save(final_chunk_index)
            
            # with open(self.index_path, 'w', encoding='utf-8') as f:
            #     # Pydantic v2. `model_dump` is the new `dict`
            #     json.dump([idx.model_dump() for idx in final_chunk_index], f, indent=2)
                
            print(f"  - Successfully indexed {len(final_chunk_index)} chunks. Saved to {self.index_path}")
            return final_chunk_index
        except Exception as e:
            import traceback
            traceback.print_exc()


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