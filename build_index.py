import os
from dotenv import load_dotenv
from rag.rag_entry import DDBRAG
from rag.text_index_manager import TextIndexManager

# 加载环境变量
load_dotenv()

# 从环境变量读取项目路径，默认为当前目录
project_path = os.getenv("PROJECT_PATH", ".")

# 使用相对路径，由 BaseIndexManager 自动拼接
index_file = ".ddb_agent/file_index.json"

index_manager = TextIndexManager(project_path=project_path, index_file=index_file)
index_manager.build_index(file_extensions=".md", max_workers=20)

