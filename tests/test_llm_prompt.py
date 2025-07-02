
from pydantic import BaseModel

from llm.llm_prompt import llm
from utils.json_parser import parse_json_string


@llm.prompt(model="openai-gpt4o")
def test_hello(name: str) -> str:
    """
    我是 {{ name }}，请问你是谁？

    """

@llm.prompt(model="deepseek-default")
def test_json_resp(name: str) -> str:
    """
    我是{{ name }}，请返回JSON格式的响应

    返回的JSON格式如下：
    ```json
    {
        "name": "{{ name }}",
        "greeting": "Hello, {{ name }}!"
    }
    ```

    """


#result = parse_json_string(test_json_resp(name="Jinzhi"))
result = test_hello("jinzhi")
print(result)