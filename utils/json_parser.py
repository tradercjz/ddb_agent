import json

def parse_json_string(json_str):
    # 去掉 JSON 字符串的 ```json 和 ``` 标记部分
    json_str  = json_str.lstrip().rstrip()  # 去掉首尾空白字符
    if json_str.startswith('```json'):
        json_str = json_str[7:]  # 去掉开头的 ```json
    if json_str.endswith('```'):
        json_str = json_str[:-3]  # 去掉结尾的 ```

    # 解析 JSON 字符串
    try:
        import re
        cleaned_json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)

        data = json.loads(cleaned_json_str)
        return data
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return None