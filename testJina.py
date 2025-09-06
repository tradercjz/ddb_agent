import pickle
import requests
import json
from langchain_text_splitters import RecursiveCharacterTextSplitter
import numpy as np
import faiss
import glob
import os

JINA_TOKEN = 'jina_e1105e8b8bff4ce4a23a9e3f66c7e501Hlb4KoyuCxtFSSM1QcE2yBAdLWVP'
DOCS_DIRECTORY = "./documentation/"

CHUNK_SIZE = 10000
CHUNK_OVERLAP = 0

FAISS_INDEX_PATH = "my_docs_advanced.index"
CHUNKS_MAPPING_PATH = "my_docs_chunks_advanced.pkl"

def embed_via_jina(text: str):
    """调用 Jina API 生成文本嵌入向量"""
    url = 'https://api.jina.ai/v1/embeddings'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + JINA_TOKEN
    }
    
    data = {
        "model": "jina-embeddings-v4",
        "task": "retrieval.passage",
        "input": [
            {"text": text},
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # 抛出HTTP错误异常
        
        result = response.json()
        print(f"API 响应状态: {response.status_code}")
        
        # 检查响应格式
        if 'data' in result and len(result['data']) > 0:
            if 'embedding' in result['data'][0]:
                return result['data'][0]['embedding']
            else:
                print(f"响应中缺少 'embedding' 字段: {result}")
                return None
        else:
            print(f"意外的API响应格式: {result}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"API 请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        print(f"原始响应: {response.text}")
        return None
    except Exception as e:
        print(f"生成嵌入向量时发生未知错误: {e}")
        return None

def main():
    markdown_splitter = RecursiveCharacterTextSplitter.from_language(
        language="markdown", 
        chunk_size=CHUNK_SIZE, 
        chunk_overlap=CHUNK_OVERLAP
    )
    
    # 递归查找所有 .md 文件
    markdown_files = glob.glob(os.path.join(DOCS_DIRECTORY, '**', '*.md'), recursive=True)
    if not markdown_files:
        print(f"警告：在目录 '{DOCS_DIRECTORY}' 中没有找到任何 .md 文件。")
        return
    
    print(f"找到了 {len(markdown_files)} 个 Markdown 文件。正在处理...")
    
    documents_as_chunked_lists = []
    all_chunks_text_flat = []
    
    for filepath in markdown_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"无法读取文件 {filepath}: {e}")
            continue
        
        chunks = markdown_splitter.split_text(content)
        if not chunks:
            print(f"  - 文档 {os.path.basename(filepath)} 未能生成文本块，已跳过。")
            continue
                
        print(f"  - 处理文档: {os.path.basename(filepath)}，生成了 {len(chunks)} 个文本块。")
                
        documents_as_chunked_lists.append(chunks)
        all_chunks_text_flat.extend(chunks)
    
    if not documents_as_chunked_lists:
        print("所有文件都未能生成文本块，程序终止。")
        return
    
    print(f"\n所有文件分块完成，共得到 {len(all_chunks_text_flat)} 个文本块，来自 {len(documents_as_chunked_lists)} 个文档。")
    
    # 🔧 关键修复：使用两个并行列表来保持对应关系
    all_embeddings = []
    successful_chunks = []  # 只保存成功处理的文本块
    failed_indices = []     # 记录失败的索引，用于调试
    
    # 处理所有文本块（这里只处理前3个作为示例）
    chunks_to_process = all_chunks_text_flat # 可以改为 all_chunks_text_flat
    
    print(f"\n开始处理 {len(chunks_to_process)} 个文本块...")
    
    for i, chunk in enumerate(chunks_to_process):
        print(f"\n处理第 {i+1}/{len(chunks_to_process)} 个文本块...")
        print(f"文本块内容预览: {chunk[:100]}...")
        
        embedding = embed_via_jina(chunk)
        
        if embedding is not None:
            # ✅ 成功：同时添加到两个列表中
            all_embeddings.append(embedding)
            successful_chunks.append(chunk)
            print(f"✅ 成功生成嵌入向量，维度: {len(embedding)}")
        else:
            # ❌ 失败：记录失败的索引，但不添加到列表中
            failed_indices.append(i)
            print(f"❌ 第 {i+1} 个文本块的嵌入向量生成失败，跳过该块")
    
    # 📊 处理结果统计
    success_count = len(all_embeddings)
    total_count = len(chunks_to_process)
    failure_count = len(failed_indices)
    
    print(f"\n📊 处理结果统计：")
    print(f"  - 总共处理: {total_count} 个文本块")
    print(f"  - 成功处理: {success_count} 个文本块")
    print(f"  - 处理失败: {failure_count} 个文本块")
    
    if failed_indices:
        print(f"  - 失败的块索引: {failed_indices}")
    
    if not all_embeddings:
        print("❌ 错误：没有成功生成任何嵌入向量，程序终止。")
        return
    
    # ✅ 验证对应关系
    assert len(all_embeddings) == len(successful_chunks), \
        f"嵌入向量数量({len(all_embeddings)})与文本块数量({len(successful_chunks)})不匹配！"
    
    print(f"\n✅ 验证通过：{len(all_embeddings)} 个嵌入向量与 {len(successful_chunks)} 个文本块完美对应")
                        
    print(f"\n向量生成完毕，开始构建 FAISS 索引...")
    
    # 转换为numpy数组
    embeddings_np = np.array(all_embeddings).astype('float32')
    print(f"嵌入向量数组形状: {embeddings_np.shape}")
            
    # 构建FAISS索引
    d = embeddings_np.shape[1]  # 向量维度
    index = faiss.IndexFlatL2(d)
    index.add(embeddings_np)
            
    print(f"FAISS 索引已构建。索引中共有 {index.ntotal} 个向量。")
    
    # 🔧 修复后的保存方式：保存正确对应的文本块
    faiss.write_index(index, FAISS_INDEX_PATH)
    with open(CHUNKS_MAPPING_PATH, 'wb') as f:
        pickle.dump(successful_chunks, f)  # 现在这个列表是正确对应的
    
    print(f"索引已保存到: {FAISS_INDEX_PATH}")
    print(f"文本块映射已保存到: {CHUNKS_MAPPING_PATH}")
    
    # 🔍 最终验证
    print(f"\n🔍 最终验证：")
    print(f"  - FAISS索引包含: {index.ntotal} 个向量")
    print(f"  - 文本块映射包含: {len(successful_chunks)} 个文本块")
    print(f"  - 数量匹配: {'✅ 是' if index.ntotal == len(successful_chunks) else '❌ 否'}")
    
    # 📝 保存处理日志（可选）
    processing_log = {
        'total_chunks': total_count,
        'successful_chunks': success_count,
        'failed_chunks': failure_count,
        'failed_indices': failed_indices,
        'embedding_dimension': d
    }
    
    with open('processing_log.json', 'w', encoding='utf-8') as f:
        json.dump(processing_log, f, indent=2, ensure_ascii=False)
    
    print(f"处理日志已保存到: processing_log.json")
    print(f"处理完成！成功处理了 {success_count} 个文本块。")

if __name__ == "__main__":
    main()