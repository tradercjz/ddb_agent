import os
import json
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class ModelConfig(BaseModel):
    """
    Represents the configuration for a single LLM.
    """
    name: str = Field(description="A unique, user-friendly name for this configuration.")
    model_name: str = Field(description="The actual model name to be passed to the API.")
    base_url: str = Field(description="The base URL of the API provider.")
    api_key: Optional[str] = Field(None, description="Direct API key (less secure).")
    api_key_env_var: Optional[str] = Field(None, description="Environment variable name for the API key (recommended).")
    model_type: Optional[str] = Field(None, description="Type of the model provider (e.g., 'openai', 'deepseek').")
    description: Optional[str] = Field(None, description="A brief description of the model.")
    max_context_tokens: Optional[int] = Field(None, description="Maximum number of tokens the model can handle in a single request. If not set, defaults to 50000.")
    log_requests: Optional[bool] = Field(False, description="Whether to log requests made to this model. Defaults to False.")

    def get_api_key(self) -> str:
        """
        Retrieves the API key, prioritizing the direct key, then the environment variable.
        """
        if self.api_key:
            return self.api_key
        if self.api_key_env_var:
            key = os.getenv(self.api_key_env_var)
            if key:
                return key
        # 如果都没有，则返回空字符串，让上层处理错误
        return ""

class ModelManager:
    """
    Loads and manages all available model configurations from a JSON file.
    """
    _models: Dict[str, ModelConfig] = {}
    _is_loaded = False

    @classmethod
    def load_models(cls, file_path: str = "models.json"):
        """
        Loads model configurations from a JSON file.
        """
        if not os.path.exists(file_path):
            print(f"Warning: Model configuration file not found at '{file_path}'.")
            cls._is_loaded = True
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                models_data = json.load(f)
            
            for config_data in models_data:
                model_config = ModelConfig(**config_data)
                if model_config.name in cls._models:
                    print(f"Warning: Duplicate model name '{model_config.name}' found. Overwriting.")
                cls._models[model_config.name] = model_config
            
            cls._is_loaded = True
            print(f"Successfully loaded {len(cls._models)} model configurations from '{file_path}'.")
        except (json.JSONDecodeError, Exception) as e:
            raise IOError(f"Failed to load or parse model configuration file '{file_path}': {e}")

    @classmethod
    def get_model_config(cls, name: str) -> Optional[ModelConfig]:
        """
        Retrieves a model configuration by its unique name.
        """
        if not cls._is_loaded:
            cls.load_models() # 自动加载
        
        return cls._models.get(name)

# 可以在模块加载时自动加载一次
ModelManager.load_models()