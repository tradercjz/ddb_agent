
from rag.rag_entry import DDBRAG
from rag.index_manager import DDBIndexManager


project_path = "./dolphindbmodules"
# 3. Build the index (only needs to be done once, or when files change)
#index_manager = DDBIndexManager(project_path=project_path, index_file="/home/jzchen/projects/ddb_agent/.ddb_agent/index.json")
#index_manager.build_index(file_extensions=".dos", max_workers = 8)


rag_agent = DDBRAG(project_path=project_path, index_file="/home/jzchen/projects/ddb_agent/.ddb_agent/index.json")

# Example query
user_query = "如何查看表磁盘占用"
final_answer = rag_agent.chat(user_query)

print("\n--- Final Answer ---")
print(final_answer)