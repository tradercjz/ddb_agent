
from rag.rag_entry import DDBRAG
from rag.text_index_manager import TextIndexManager

project_path = "./dolphindbmodules"

index_manager = TextIndexManager(project_path=project_path, index_file="/home/jzchen/ddb_agent/.ddb_agent/file_index.json")
index_manager.build_index(file_extensions=".md", max_workers = 10)

