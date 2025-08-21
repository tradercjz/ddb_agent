# FILE: ./agent/file_handler.py

import os
from typing import Tuple, Optional, Dict
from utils.text_extractor import extract_text_from_file
from token_counter import count_tokens

# 定义一个合理的阈值来区分大小文件
SMALL_FILE_TOKEN_THRESHOLD = 32000

class FileHandler:
    """
    封装了所有与文件处理相关的逻辑，如文本提取、Token计算等。
    """
    def process_file(self, file_path: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        处理一个文件路径，提取其内容，并判断其注入类型。

        返回: 
            - success (bool): 是否成功处理。
            - message (str): 给用户的反馈信息。
            - context_obj (Optional[Dict]): 用于存储在 session 中的上下文对象。
        """
        # 扩展用户路径（例如 ~）并检查文件是否存在
        expanded_path = os.path.expanduser(file_path)
        if not os.path.exists(expanded_path):
            return False, f"File not found: {file_path}", None

        try:
            # 1. 从各种文件类型中提取纯文本
            content = extract_text_from_file(expanded_path)
            if content is None:
                return False, f"Could not extract text from {file_path}. The file might be empty, corrupted, or of an unsupported type.", None
            
            # 2. 计算文本的 Token 数量
            num_tokens = count_tokens(content)

            # 3. 根据 Token 数量决定处理策略
            if num_tokens <= SMALL_FILE_TOKEN_THRESHOLD:
                # 对于小文件，我们直接将其内容注入
                context_obj = {
                    "type": "full_content",
                    "content": content,
                    "tokens": num_tokens
                }
                msg = f"File '{file_path}' ({num_tokens} tokens) has been fully loaded into the context."
                return True, msg, context_obj
            else:
                # 对于大文件，我们（在阶段二）将对其进行索引
                # 目前，我们只返回一个提示信息
                # 注意：我们返回成功(True)，因为“识别出大文件”本身是一个成功的操作
                msg = f"File '{file_path}' ({num_tokens} tokens) is too large for direct injection. RAG indexing is required (feature in development)."
                # 返回的 context_obj 为 None，表示不进行注入
                return True, msg, None 

        except Exception as e:
            return False, f"An unexpected error occurred while processing file {file_path}: {e}", None