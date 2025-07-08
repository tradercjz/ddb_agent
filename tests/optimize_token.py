import json

# 假设 JSON 数据存储在 'data.json' 文件中
with open('/home/jzchen/ddb_agent/test_content.txt', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 获取 content 字段并统计其长度
content_length = len(data['messages'][0]['content'])


print("data:", data)
print(f"The length of content is: {content_length}")
