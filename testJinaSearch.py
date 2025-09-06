import json
import os
import faiss
import numpy as np
import pickle
import requests

JINA_TOKEN = 'jina_e1105e8b8bff4ce4a23a9e3f66c7e501Hlb4KoyuCxtFSSM1QcE2yBAdLWVP'
DOCS_DIRECTORY = "./documentation/"

CHUNK_SIZE = 10000
CHUNK_OVERLAP = 0

FAISS_INDEX_PATH = "my_docs_advanced.index"
CHUNKS_MAPPING_PATH = "my_docs_chunks_advanced.pkl"

def search_via_jina(text: str):
    """调用 Jina API 生成文本嵌入向量"""
    url = 'https://api.jina.ai/v1/embeddings'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + JINA_TOKEN
    }
    
    data = {
        "model": "jina-embeddings-v4",
        "task": "retrieval.query",
        "input": [text]
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # 抛出HTTP错误异常
        
        result = response.json()
        print(f"API 响应状态: {response.status_code}")
        
        # 检查响应格式
        if 'data' in result and len(result['data']) > 0:
            if 'embedding' in result['data'][0]:
                embedding = result['data'][0]['embedding']
                print(f"成功获取查询向量，维度: {len(embedding)}")
                return embedding
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

def search_knowledge_base(query: str, k: int = 3):
    """
    在知识库中搜索与查询最相关的 k 个结果。
    """
    print(f"正在执行 k-NN 检索，查询: '{query}', k={k}")
    
    # 1. 加载存储的信息
    print("正在从磁盘加载 FAISS 索引和文本文档...")
    try:
        index = faiss.read_index(FAISS_INDEX_PATH)
        with open(CHUNKS_MAPPING_PATH, 'rb') as f:
            documents = pickle.load(f)
        print(f"成功加载索引，包含 {index.ntotal} 个向量")
        print(f"成功加载 {len(documents)} 个文档块")
    except FileNotFoundError as e:
        print(f"错误：索引文件未找到 - {e}")
        print("请先运行构建索引的脚本。")
        return []
    except Exception as e:
        print(f"加载索引时发生错误: {e}")
        return []

    # 2. 检查 k 值是否合理
    if k > index.ntotal:
        print(f"警告：k={k} 大于索引中的向量数量 ({index.ntotal})，将 k 设置为 {index.ntotal}")
        k = index.ntotal
    
    # 3. 为用户查询计算向量
    print("正在为查询生成嵌入向量...")
    query_embedding = search_via_jina(query)
    
    if query_embedding is None:
        print("错误：无法为查询生成嵌入向量")
        return []
    
    # 4. 转换为 FAISS 需要的格式
    # 关键修复：确保是二维数组 (1, embedding_dim)
    query_vector_np = np.array([query_embedding]).astype('float32')  # 注意这里用 [query_embedding] 包装成二维
    print(f"查询向量形状: {query_vector_np.shape}")
    
    # 5. 验证向量维度
    expected_dim = index.d  # FAISS索引的向量维度
    actual_dim = query_vector_np.shape[1]
    if actual_dim != expected_dim:
        print(f"错误：查询向量维度 ({actual_dim}) 与索引向量维度 ({expected_dim}) 不匹配")
        return []
    
    # 6. 执行 k-NN 搜索
    print("正在 FAISS 索引中进行搜索...")
    try:
        distances, indices = index.search(query_vector_np, k)
        print(f"搜索完成，返回 {len(indices[0])} 个结果")
    except Exception as e:
        print(f"搜索过程中发生错误: {e}")
        return []
    
    # 7. 整理并返回结果
    results = []
    print(f"\n--- 检索结果 (共 {k} 个) ---")
    
    # `indices` 是一个二维数组，我们需要取第一行
    results_indices = indices[0]
    results_distances = distances[0]
    
    for i, (idx, distance) in enumerate(zip(results_indices, results_distances)):
        # 检查索引是否有效
        if idx >= len(documents):
            print(f"警告：索引 {idx} 超出文档范围，跳过")
            continue
            
        result_text = documents[idx]
        results.append({
            'rank': i + 1,
            'index': int(idx),
            'distance': float(distance),
            'text': result_text
        })
        
        print(f"\nTop {i+1} (索引: {idx}, 距离: {distance:.4f}):")
        print(f"文本预览: {result_text[:200]}{'...' if len(result_text) > 200 else ''}")
        print("-" * 80)
    
    return results

def interactive_search():
    """交互式搜索模式"""
    print("=== 知识库交互式搜索 ===")
    print("输入 'quit' 或 'exit' 退出")
    
    while True:
        try:
            query = input("\n请输入搜索查询: ").strip()
            if query.lower() in ['quit', 'exit', '退出']:
                print("再见！")
                break
            
            if not query:
                print("请输入有效的查询内容")
                continue
            
            k = input("返回结果数量 (默认3): ").strip()
            try:
                k = int(k) if k else 3
            except ValueError:
                k = 3
                print("使用默认值 k=3")
            
            results = search_knowledge_base(query, k)
            
            if not results:
                print("未找到相关结果")
            
        except KeyboardInterrupt:
            print("\n\n程序被中断，再见！")
            break
        except Exception as e:
            print(f"发生未知错误: {e}")

if __name__ == "__main__":
    # 可以选择单次搜索或交互式搜索
    
    # 方式1: 单次搜索
    # print("=== 单次搜索模式 ===")
    # user_query = "failed to open chunks怎么处理"
    # results = search_knowledge_base(user_query, k=2)
    
    # 方式2: 交互式搜索 (取消注释下面的行来启用)
    interactive_search()