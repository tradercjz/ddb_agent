import os
import random
from dotenv import load_dotenv
from rag.text_index_manager import TextIndexManager

# 加载环境变量
load_dotenv()

# 从环境变量读取项目路径，默认为当前目录
project_path = os.getenv("PROJECT_PATH", ".")

# 使用测试专用的索引文件，避免覆盖正式索引
test_index_file = ".ddb_agent/test_file_index.json"

# 创建索引管理器实例
index_manager = TextIndexManager(project_path=project_path, index_file=test_index_file)

# 先发现所有 .md 文件
print("Discovering all .md files...")
all_md_files = index_manager._discover_files(file_extensions=".md")

if not all_md_files:
    print("No .md files found in the project.")
    exit(0)

print(f"Found {len(all_md_files)} total .md files.")

# 随机抽取50个文件（如果文件总数少于50，则使用全部文件）
sample_size = min(50, len(all_md_files))
sampled_files = random.sample(all_md_files, sample_size)

print(f"Randomly selected {sample_size} files for testing.")
print("=" * 60)

# 临时修改 _discover_files 方法的返回值，只处理抽样的文件
# 保存原始方法
original_discover_files = index_manager._discover_files

# 定义新的 _discover_files 方法，返回抽样的文件
def mock_discover_files(file_extensions=None):
    return sampled_files

# 替换方法
index_manager._discover_files = mock_discover_files

# 执行索引构建
# max_workers 从环境变量 BUILD_INDEX_WORKER 读取，默认为 4
index_manager.build_index(file_extensions=".md")

# 恢复原始方法
index_manager._discover_files = original_discover_files

print("=" * 60)
print(f"Test completed! Index saved to: {os.path.join(project_path, test_index_file)}")
print(f"Total files indexed: {len(index_manager.project_index.files)}")
