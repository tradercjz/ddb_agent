import os
import sys
import json
import tempfile
import shutil
from typing import List, Dict, Any

# -- Add the project root to the Python path --
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
# ---------------------------------------------

from rag.types import ProjectIndex, BaseIndexModel
from rag.embedding_models import VolcanoEmbedding

def add_embeddings_to_index(index_file_path: str, batch_size: int = 16):
    """
    Loads an existing index file, generates embeddings for entries that
    are missing them, and saves the updated index back to the file.

    Args:
        index_file_path: The full path to the 'file_index.json'.
        batch_size: The number of summaries to send to the embedding API at once.
    """
    # 输入验证
    if batch_size <= 0:
        print(f"Error: batch_size must be positive, got {batch_size}")
        return
    
    print(f"Loading existing index from: {index_file_path}")
    if not os.path.exists(index_file_path):
        print(f"Error: Index file not found at {index_file_path}")
        return

    # 加载和验证索引文件
    try:
        with open(index_file_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        project_index = ProjectIndex.model_validate(index_data)
        print(f"Successfully loaded index with {len(project_index.files)} entries")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in index file: {e}")
        return
    except Exception as e:
        print(f"Error loading or validating index file: {e}")
        return

    # 初始化嵌入模型
    try:
        embedding_model = VolcanoEmbedding()
        print("VolcanoEmbedding model initialized successfully.")
    except ValueError as e:
        print(f"Fatal Error: Could not initialize embedding model. {e}")
        print("Please ensure the ARK_API_KEY environment variable is set.")
        return
    except Exception as e:
        print(f"Unexpected error initializing embedding model: {e}")
        return

    # 识别需要嵌入的条目
    entries_to_embed: List[BaseIndexModel] = []
    for item in project_index.files:
        # if getattr(item, 'embedding', None) is None:
        #     if hasattr(item, 'summary') and item.summary and item.summary.strip():
        #        entries_to_embed.append(item)
        entries_to_embed.append(item)

    if not entries_to_embed:
        print("All index entries already have embeddings. No action needed.")
        return

    print(f"Found {len(entries_to_embed)} index entries that need embeddings.")

    # 分批处理以避免内存问题和API限制
    summaries_to_embed = [item.summary for item in entries_to_embed]
    all_embeddings = []
    
    print(f"Generating embeddings in batches of {batch_size}...")
    
    try:
        for i in range(0, len(summaries_to_embed), batch_size):
            batch_summaries = summaries_to_embed[i:i + batch_size]
            batch_start = i + 1
            batch_end = min(i + batch_size, len(summaries_to_embed))
            
            print(f"Processing batch {batch_start}-{batch_end} of {len(summaries_to_embed)}...")
            
            try:
                batch_embeddings = embedding_model.embed_documents(batch_summaries)
                
                # 验证返回的嵌入向量数量
                if len(batch_embeddings) != len(batch_summaries):
                    print(f"Warning: Expected {len(batch_summaries)} embeddings, got {len(batch_embeddings)}")
                    print("Skipping this batch to maintain data consistency.")
                    continue
                
                all_embeddings.extend(batch_embeddings)
                print(f"Successfully generated {len(batch_embeddings)} embeddings for this batch")
                
            except Exception as batch_e:
                print(f"Error processing batch {batch_start}-{batch_end}: {batch_e}")
                print("Continuing with next batch...")
                # 为失败的批次添加 None 占位符
                all_embeddings.extend([None] * len(batch_summaries))
                continue
                
    except Exception as e:
        print(f"Fatal Error during embedding generation: {e}")
        return

    # 验证总体结果
    if len(all_embeddings) != len(entries_to_embed):
        print(f"Error: Mismatch between entries ({len(entries_to_embed)}) and embeddings ({len(all_embeddings)})")
        return

    # 分配嵌入向量回索引条目
    updated_count = 0
    failed_count = 0
    
    for item, embedding in zip(entries_to_embed, all_embeddings):
        if embedding is not None:
            item.embedding = embedding
            updated_count += 1
        else:
            failed_count += 1
            print(f"Warning: Failed to generate embedding for item with summary: {item.summary[:50]}...")

    print(f"Successfully added embeddings to {updated_count} entries.")
    if failed_count > 0:
        print(f"Failed to generate embeddings for {failed_count} entries.")

    # 原子性保存：先写入临时文件，然后替换原文件
    print(f"Saving updated index back to {index_file_path}...")
    try:
        # 创建临时文件
        temp_dir = os.path.dirname(index_file_path)
        with tempfile.NamedTemporaryFile(
            mode='w', 
            encoding='utf-8', 
            dir=temp_dir, 
            delete=False,
            suffix='.tmp'
        ) as temp_file:
            temp_file.write(project_index.model_dump_json(indent=2))
            temp_file_path = temp_file.name
        
        # 原子性替换原文件
        shutil.move(temp_file_path, index_file_path)
        print("Index successfully updated and saved!")
        
    except Exception as e:
        print(f"Error saving updated index file: {e}")
        # 清理临时文件
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass
        return


if __name__ == "__main__":
    target_index_file = os.path.join(project_root, '.ddb_agent', 'file_index.json')
    add_embeddings_to_index(target_index_file)