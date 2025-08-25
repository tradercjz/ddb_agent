from dataclasses import dataclass
import json
from openai import OpenAI
from typing import Generator, List, Dict, Any, Literal, Optional, Union
import os
from loguru import logger

@dataclass
class StreamChunk:
    type: Literal["reasoning", "content", "metadata", "error"]
    data: any

@dataclass 
class LLMResponse:
    """通用LLM响应结果容器"""
    success: bool
    content: str = ""  # 原始响应内容
    reasoning_content: str = ""  # 推理内容
    error_message: str = ""
    error_type: str = ""
    metadata: Dict[str, Any] = None  # 可能的元数据

class LLMClient:
    """LLM客户端，处理与OpenAI API的交互"""
    
    def __init__(self, api_key: str, base_url: str, logger=None):
        """初始化LLM客户端
        
        Args:
            api_key: API密钥
            base_url: API基础URL
            logger: 日志记录器
        """
        if not api_key:
            raise ValueError("API key must be provided.")
        if not base_url:
            raise ValueError("Base URL must be provided.")
        
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.logger = logger

    def _log_request(self, conversation_history: List[Dict[str, str]], model: str):
        """Helper method to log the request payload."""
        try:
            # 使用 .bind(llm_request=True) 来标记这条日志
            # 这样我们的文件处理器就能通过 filter 捕获它
            request_logger = logger.bind(llm_request=True)
            
            # 格式化日志内容
            log_content = {
                "model": model,
                "messages": conversation_history
            }
            # 使用 pretty-printed JSON 格式，便于阅读
            request_logger.debug(f"\n{json.dumps(log_content, indent=2, ensure_ascii=False)}")
        except Exception as e:
            logger.warning(f"Failed to log LLM request: {e}")
            
    def generate_response(
        self, 
        conversation_history: List[Dict[str, str]],
        model: Optional[str] = None,
        log_requests: bool = False
    ) ->  Generator[StreamChunk, None, LLMResponse]:
        """从LLM获取响应
        
        Args:
            conversation_history: 对话历史
            
        Returns:
            LLMResponse: llm原始返回
        """
        try:
            target_model = model or os.getenv("LLM_MODEL")
            if not target_model:
                raise ValueError("No model specified and LLM_MODEL environment variable is not set.")
            
            if log_requests:
                self._log_request(conversation_history, target_model)
            
            stream = self.client.chat.completions.create(
                model=target_model,
                messages=conversation_history,
                max_completion_tokens=8000,
                stream=True
            )

            if self.logger:
                self.logger.info("Thinking...")
            
            reasoning_started = False
            reasoning_content = ""
            final_content = ""

            for chunk in stream:
                delta = chunk.choices[0].delta

                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    if self.logger and not reasoning_started:
                        self.logger.info("Reasoning:")
                        reasoning_started = True
                    reasoning_content += delta.reasoning_content
                    yield StreamChunk(type="reasoning", data=delta.reasoning_content)
                elif hasattr(delta, 'content') and delta.content:
                    final_content += delta.content
                    yield StreamChunk(type="content", data=delta.content)

            if self.logger:
                self.logger.info(f"Assistant> {final_content}")

            return LLMResponse(
                    success=True,
                    content=final_content,
                    reasoning_content=reasoning_content,
                    metadata={"model": target_model}
                )
            

        except Exception as e:
            error_msg = f"Model API error: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            return LLMResponse(success=False,error_message=error_msg,error_type=type(e).__name__)
            
        
class LLMClientManager:
    """
    管理和缓存多个LLMClient实例。
    """
    _clients: Dict[str, LLMClient] = {}

    @classmethod
    def get_client(cls, api_key: Optional[str] = None, base_url: Optional[str] = None, logger=None) -> LLMClient:
        """
        获取一个LLMClient实例。如果已存在相同配置的实例，则从缓存返回。
        
        Args:
            api_key: API密钥。如果为None，则从环境变量 LLM_API_KEY 获取。
            base_url: API基础URL。如果为None，则从环境变量 LLM_BASE_URL 获取。
            logger: 日志记录器。
            
        Returns:
            LLMClient实例。
        """
        # 确定最终的配置
        final_api_key = api_key or os.getenv("LLM_API_KEY")
        final_base_url = base_url or os.getenv("LLM_BASE_URL")

        if not final_api_key or not final_base_url:
            raise ValueError("API key and Base URL must be provided either as arguments or environment variables.")

        # 使用base_url作为缓存的key，通常一个base_url对应一个服务商
        cache_key = final_base_url

        if cache_key not in cls._clients:
            print(f"Creating new LLMClient for: {final_base_url}")
            cls._clients[cache_key] = LLMClient(
                api_key=final_api_key,
                base_url=final_base_url,
                logger=logger
            )
        
        return cls._clients[cache_key]