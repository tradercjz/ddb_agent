# file: ddb_agent/token_counter.py

import os
from typing import Dict, Optional, Callable
from functools import lru_cache
import transformers

# --- Tokenizer 注册表和加载器 ---

# 1. 注册表：存储已加载的Tokenizer实例
_tokenizer_cache: Dict[str, transformers.PreTrainedTokenizer] = {}

# 2. Tokenizer加载函数定义
#    这是一个可扩展的设计，我们可以为不同类型的模型定义不同的加载函数
def _load_deepseek_tokenizer(model_path: str) -> transformers.PreTrainedTokenizer:
    """
    加载 DeepSeek 系列模型的 Tokenizer。
    """
    print(f"Loading DeepSeek tokenizer from: {model_path}...")
    try:
        # trust_remote_code=True 是因为 DeepSeek 的 tokenizer 可能包含自定义代码
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            model_path, trust_remote_code=True
        )
        print("Tokenizer loaded successfully.")
        return tokenizer
    except Exception as e:
        raise IOError(f"Failed to load tokenizer from {model_path}. "
                      f"Please ensure the tokenizer files are correctly placed. Error: {e}")

# 3. 模型名称到加载器和路径的映射
#    这个字典让我们可以为不同的模型别名配置不同的加载方式和路径
TOKENIZER_CONFIGS = {
    # 默认的 DeepSeek 模型别名
    "deepseek": {
        "loader": _load_deepseek_tokenizer,
        "path": "./tokenizers/deepseek" # 假设的路径
    },
    # 未来可以轻松扩展，例如：
    # "llama3": {
    #     "loader": _load_llama_tokenizer,
    #     "path": "./tokenizers/llama3"
    # }
}

def get_tokenizer(model_name: str) -> Optional[transformers.PreTrainedTokenizer]:
    """
    根据模型名称获取（加载并缓存）一个Tokenizer实例。

    Args:
        model_name: 在 TOKENIZER_CONFIGS 中定义的模型别名。

    Returns:
        一个 transformers Tokenizer 实例，如果找不到则返回 None。
    """
    if model_name in _tokenizer_cache:
        return _tokenizer_cache[model_name]

    config = TOKENIZER_CONFIGS.get(model_name)
    if not config:
        #print(f"Warning: No tokenizer configuration found for model '{model_name}'. "
             # f"Token counting may be inaccurate.")
        return None

    loader_func = config["loader"]
    path = config["path"]

    if not os.path.isdir(path):
        print(f"Warning: Tokenizer directory not found for model '{model_name}' at path '{path}'.")
        return None

    try:
        tokenizer = loader_func(path)
        _tokenizer_cache[model_name] = tokenizer
        return tokenizer
    except Exception as e:
        print(f"Error getting tokenizer for model '{model_name}': {e}")
        return None


# --- 统一的 Token 计数接口 ---

# 使用 lru_cache 进一步对计数结果进行缓存，提高对相同文本计数的性能
@lru_cache(maxsize=1024)
def count_tokens(text: str, model_name: str = "deepseek-default") -> int:
    """
    计算给定文本的 token 数量。

    Args:
        text: 要计算 token 的文本。
        model_name: 要使用的模型名称（别名），默认为 'deepseek-default'。
                    这个名称应在 TOKENIZER_CONFIGS 中有定义。

    Returns:
        token 的数量。如果找不到对应的 tokenizer，则会基于字符数进行粗略估算。
    """
    tokenizer = get_tokenizer(model_name)

    if tokenizer:
        try:
            # 使用 tokenizer.encode，因为它通常比 __call__ 更直接地返回 token ID 列表
            return len(tokenizer.encode(text))
        except Exception as e:
            print(f"Error encoding text with tokenizer for '{model_name}': {e}")
            # fall back to estimation
            return _estimate_tokens(text)
    else:
        # 如果没有找到 tokenizer，提供一个回退的估算方法
        return _estimate_tokens(text)

def _estimate_tokens(text: str) -> int:
    """
    一个简单的 token 估算方法，当没有可用 tokenizer 时的后备方案。
    对于英文，一个token约等于4个字符。对于中文，一个token约等于1.5-2个字符。
    我们取一个粗略的平均值。
    """
    return len(text) // 3