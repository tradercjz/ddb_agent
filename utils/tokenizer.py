# file: utils/tokenizer.py

import re
from typing import Set

# 尝试导入 jieba，如果失败则给出提示
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    print("Warning: `jieba` library not found. Chinese tokenization will be suboptimal. "
          "Please install it with `pip install jieba`.")

def is_contains_chinese(text: str) -> bool:
    """
    Checks if a string contains any Chinese characters.
    """
    # \u4e00-\u9fa5 是中文字符的Unicode范围
    return bool(re.search(r'[\u4e00-\u9fa5]', text))

def smart_tokenize(text: str) -> Set[str]:
    """
    Tokenizes text intelligently based on its content.
    - Uses jieba for text containing Chinese characters.
    - Uses regex for English-only text.
    Returns a set of lowercased tokens.
    """
    text_lower = text.lower()
    
    if JIEBA_AVAILABLE and is_contains_chinese(text):
        # 使用 jieba 进行中文分词 (搜索引擎模式)
        # cut_for_search 会切分出更细粒度的词，适合搜索
        tokens = jieba.cut_for_search(text_lower)
        # 过滤掉单个字符和停用词（可选，但推荐）
        # 这里简单过滤掉长度为1的词
        return {token for token in tokens if len(token.strip()) > 1}
    else:
        # 对纯英文使用正则表达式
        return set(re.findall(r'\w+', text_lower))