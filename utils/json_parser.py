import datetime
import json
import os

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
        error_time = datetime.datetime.now()
        print(f"Error decoding JSON at {error_time.isoformat()}: {e}")

        try:
            error_log_dir = os.path.join(os.path.expanduser("~"), ".ddb_agent", "error_logs")
            # 确保错误日志目录存在
            os.makedirs(error_log_dir, exist_ok=True)

            # 创建一个带时间戳的唯一文件名
            # 格式: error_YYYYMMDD_HHMMSS_microseconds.log
            filename = f"error_{error_time.strftime('%Y%m%d_%H%M%S_%f')}.log"
            filepath = os.path.join(error_log_dir, filename)

            # 将详细信息写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("--- JSON Decode Error Log ---\n\n")
                f.write(f"Timestamp: {error_time.isoformat()}\n")
                f.write(f"Error Message: {e}\n")
                f.write("\n--- Problematic String (after cleaning markdown) ---\n")
                f.write(cleaned_json_str)

            print(f"The problematic string and error details have been saved to: {filepath}")

        except Exception as log_e:
            # 如果连写入日志文件都失败了，打印一个严重的警告
            print(f"CRITICAL: Failed to write error log file to '{error_log_dir}'. Error: {log_e}")