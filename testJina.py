import pickle
import requests
import json
from langchain_text_splitters import RecursiveCharacterTextSplitter
import numpy as np
import faiss
import glob
import os
import signal
import sys
import time
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import List, Optional, Tuple, Dict, Any
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('embedding_process.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置参数
JINA_TOKEN = 'jina_e1105e8b8bff4ce4a23a9e3f66c7e501Hlb4KoyuCxtFSSM1QcE2yBAdLWVP'
DOCS_DIRECTORY = "./documentation/"

CHUNK_SIZE = 10000
CHUNK_OVERLAP = 0

FAISS_INDEX_PATH = "my_docs_advanced.index"
CHUNKS_MAPPING_PATH = "my_docs_chunks_advanced.pkl"
CHECKPOINT_PATH = "embedding_checkpoint.pkl"

# 并发配置
MAX_CONCURRENT_REQUESTS = 5  # 同时进行的最大请求数
REQUEST_DELAY = 0.1  # 请求间隔（秒）
MAX_RETRIES = 3      # 失败重试次数
CHECKPOINT_INTERVAL = 10  # 每处理多少个块保存一次检查点

class EmbeddingProcessor:
    def __init__(self):
        self.all_embeddings = []
        self.successful_chunks = []
        self.failed_indices = []
        self.processed_count = 0
        self.total_count = 0
        self.lock = Lock()  # 用于线程安全
        self.should_stop = False  # 控制优雅停止
        self.start_time = None
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理 Ctrl+C 和其他终止信号"""
        signal_names = {signal.SIGINT: 'SIGINT (Ctrl+C)', signal.SIGTERM: 'SIGTERM'}
        signal_name = signal_names.get(signum, f'Signal {signum}')
        
        logger.warning(f"\n🛑 收到 {signal_name} 信号，正在优雅停止...")
        logger.info("正在保存当前进度，请稍候...")
        
        self.should_stop = True
        
        # 保存当前状态
        self._save_checkpoint()
        
        logger.info(f"✅ 当前进度已保存到 {CHECKPOINT_PATH}")
        logger.info(f"📊 已处理: {self.processed_count}/{self.total_count} 个文本块")
        logger.info("下次运行时会从检查点继续...")
        
        sys.exit(0)
    
    def _save_checkpoint(self):
        """保存检查点"""
        try:
            checkpoint_data = {
                'all_embeddings': self.all_embeddings,
                'successful_chunks': self.successful_chunks,
                'failed_indices': self.failed_indices,
                'processed_count': self.processed_count,
                'total_count': self.total_count,
                'timestamp': datetime.now().isoformat()
            }
            
            with open(CHECKPOINT_PATH, 'wb') as f:
                pickle.dump(checkpoint_data, f)
            logger.info(f"✅ 检查点已保存 ({len(self.successful_chunks)} 个成功块)")
        except Exception as e:
            logger.error(f"❌ 保存检查点失败: {e}")
    
    def _load_checkpoint(self) -> bool:
        """加载检查点"""
        try:
            if not os.path.exists(CHECKPOINT_PATH):
                return False
                
            with open(CHECKPOINT_PATH, 'rb') as f:
                checkpoint_data = pickle.load(f)
            
            self.all_embeddings = checkpoint_data['all_embeddings']
            self.successful_chunks = checkpoint_data['successful_chunks']
            self.failed_indices = checkpoint_data['failed_indices']
            self.processed_count = checkpoint_data['processed_count']
            
            logger.info(f"✅ 从检查点恢复: 已处理 {self.processed_count} 个块，成功 {len(self.successful_chunks)} 个")
            return True
            
        except Exception as e:
            logger.warning(f"⚠️ 加载检查点失败: {e}，将从头开始")
            return False

def embed_via_jina_sync(text: str, max_retries: int = MAX_RETRIES) -> Optional[List[float]]:
    """同步版本的 Jina API 调用，带重试机制"""
    url = 'https://api.jina.ai/v1/embeddings'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + JINA_TOKEN
    }
    
    data = {
        "model": "jina-embeddings-v4",
        "task": "retrieval.passage",
        "input": [{"text": text}]
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url, 
                headers=headers, 
                data=json.dumps(data),
                timeout=30  # 30秒超时
            )
            response.raise_for_status()
            
            result = response.json()
            
            if 'data' in result and len(result['data']) > 0:
                if 'embedding' in result['data'][0]:
                    return result['data'][0]['embedding']
            
            logger.warning(f"意外的API响应格式: {result}")
            return None
            
        except requests.exceptions.Timeout:
            logger.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避
        except requests.exceptions.RequestException as e:
            logger.warning(f"API请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"未知错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    return None

def process_chunk_with_index(args: Tuple[int, str, EmbeddingProcessor]) -> Tuple[int, bool, Optional[List[float]], str]:
    """处理单个文本块，返回 (索引, 是否成功, 嵌入向量, 文本)"""
    index, chunk, processor = args
    
    # 检查是否应该停止
    if processor.should_stop:
        return index, False, None, chunk
    
    try:
        # 添加请求间隔
        time.sleep(REQUEST_DELAY)
        
        logger.info(f"🔄 处理块 {index + 1}: {chunk[:50]}...")
        embedding = embed_via_jina_sync(chunk)
        
        if embedding is not None:
            logger.info(f"✅ 块 {index + 1} 处理成功，向量维度: {len(embedding)}")
            return index, True, embedding, chunk
        else:
            logger.warning(f"❌ 块 {index + 1} 处理失败")
            return index, False, None, chunk
            
    except Exception as e:
        logger.error(f"❌ 块 {index + 1} 处理异常: {e}")
        return index, False, None, chunk

def process_chunks_concurrent(chunks: List[str], processor: EmbeddingProcessor) -> None:
    """并发处理文本块"""
    processor.total_count = len(chunks)
    
    # 创建任务参数
    tasks = [(i, chunk, processor) for i, chunk in enumerate(chunks) 
                if i >= processor.processed_count]  # 跳过已处理的
    
    if not tasks:
        logger.info("✅ 所有块都已处理完成")
        return
    
    logger.info(f"🚀 开始并发处理 {len(tasks)} 个文本块 (并发数: {MAX_CONCURRENT_REQUESTS})")
    
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
        # 提交所有任务
        future_to_index = {
            executor.submit(process_chunk_with_index, task): task[0] 
            for task in tasks
        }
        
        # 处理完成的任务
        for future in as_completed(future_to_index):
            if processor.should_stop:
                logger.info("🛑 检测到停止信号，取消剩余任务...")
                # 取消未完成的任务
                for f in future_to_index:
                    f.cancel()
                break
            
            try:
                index, success, embedding, chunk = future.result()
                
                with processor.lock:  # 线程安全更新
                    processor.processed_count = max(processor.processed_count, index + 1)
                    
                    if success and embedding is not None:
                        processor.all_embeddings.append(embedding)
                        processor.successful_chunks.append(chunk)
                    else:
                        processor.failed_indices.append(index)
                    
                    # 定期保存检查点
                    if len(processor.successful_chunks) % CHECKPOINT_INTERVAL == 0:
                        processor._save_checkpoint()
                    
                    # 显示进度
                    success_count = len(processor.successful_chunks)
                    total_processed = processor.processed_count
                    progress = (total_processed / processor.total_count) * 100
                    
                    logger.info(f"📈 进度: {total_processed}/{processor.total_count} "
                                f"({progress:.1f}%), 成功: {success_count}")
                    
            except Exception as e:
                index = future_to_index[future]
                logger.error(f"❌ 处理块 {index} 时发生异常: {e}")
                with processor.lock:
                    processor.failed_indices.append(index)

def main():
    logger.info("🚀 启动健壮的向量化处理程序")
    
    processor = EmbeddingProcessor()
    processor.start_time = time.time()
    
    # 尝试从检查点恢复
    resumed_from_checkpoint = processor._load_checkpoint()
    
    # 如果没有从检查点恢复，进行文件处理
    if not resumed_from_checkpoint:
        logger.info("📂 扫描 Markdown 文件...")
        
        markdown_splitter = RecursiveCharacterTextSplitter.from_language(
            language="markdown", 
            chunk_size=CHUNK_SIZE, 
            chunk_overlap=CHUNK_OVERLAP
        )
        
        markdown_files = glob.glob(os.path.join(DOCS_DIRECTORY, '**', '*.md'), recursive=True)
        if not markdown_files:
            logger.error(f"❌ 在目录 '{DOCS_DIRECTORY}' 中没有找到任何 .md 文件")
            return
        
        logger.info(f"📄 找到了 {len(markdown_files)} 个 Markdown 文件")
        
        all_chunks_text_flat = []
        for filepath in markdown_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                chunks = markdown_splitter.split_text(content)
                if chunks:
                    logger.info(f"  - {os.path.basename(filepath)}: {len(chunks)} 个块")
                    all_chunks_text_flat.extend(chunks)
                    
            except Exception as e:
                logger.error(f"❌ 无法读取文件 {filepath}: {e}")
        
        if not all_chunks_text_flat:
            logger.error("❌ 没有生成任何文本块")
            return
        
        logger.info(f"📝 总共生成了 {len(all_chunks_text_flat)} 个文本块")
        
        # 限制处理数量用于测试
        chunks_to_process = all_chunks_text_flat # 改为 all_chunks_text_flat 处理所有
        logger.info(f"🎯 将处理 {len(chunks_to_process)} 个文本块")
    else:
        # 从检查点数据中获取原始块数据
        logger.warning("⚠️ 从检查点恢复时，需要重新读取原始文档以获取所有块")
        # 这里可以改进为在检查点中保存所有原始块
        logger.info("💡 建议：手动设置 chunks_to_process 或重新读取文档")
        return
    
    try:
        # 开始并发处理
        logger.info("🔄 开始并发处理文本块...")
        process_chunks_concurrent(chunks_to_process, processor)
        
        # 处理完成统计
        elapsed_time = time.time() - processor.start_time
        success_count = len(processor.successful_chunks)
        total_count = len(chunks_to_process)
        failure_count = len(processor.failed_indices)
        
        logger.info(f"\n📊 处理完成统计:")
        logger.info(f"  - 总耗时: {elapsed_time:.1f} 秒")
        logger.info(f"  - 总共处理: {total_count} 个文本块")
        logger.info(f"  - 成功处理: {success_count} 个")
        logger.info(f"  - 处理失败: {failure_count} 个")
        logger.info(f"  - 成功率: {(success_count/total_count*100):.1f}%")
        
        if processor.failed_indices:
            logger.warning(f"  - 失败的块索引: {processor.failed_indices[:10]}{'...' if len(processor.failed_indices) > 10 else ''}")
        
        if not processor.all_embeddings:
            logger.error("❌ 没有成功生成任何嵌入向量")
            return
        
        # 构建 FAISS 索引
        logger.info("🔨 构建 FAISS 索引...")
        embeddings_np = np.array(processor.all_embeddings).astype('float32')
        
        d = embeddings_np.shape[1]
        index = faiss.IndexFlatL2(d)
        index.add(embeddings_np)
        
        logger.info(f"✅ FAISS 索引构建完成，包含 {index.ntotal} 个向量")
        
        # 保存结果
        logger.info("💾 保存结果...")
        faiss.write_index(index, FAISS_INDEX_PATH)
        
        with open(CHUNKS_MAPPING_PATH, 'wb') as f:
            pickle.dump(processor.successful_chunks, f)
        
        # 保存处理日志
        processing_log = {
            'timestamp': datetime.now().isoformat(),
            'total_chunks': total_count,
            'successful_chunks': success_count,
            'failed_chunks': failure_count,
            'failed_indices': processor.failed_indices,
            'embedding_dimension': d,
            'processing_time_seconds': elapsed_time,
            'concurrent_workers': MAX_CONCURRENT_REQUESTS
        }
        
        with open('processing_log.json', 'w', encoding='utf-8') as f:
            json.dump(processing_log, f, indent=2, ensure_ascii=False)
        
        # 清理检查点文件
        if os.path.exists(CHECKPOINT_PATH):
            os.remove(CHECKPOINT_PATH)
            logger.info("🧹 清理检查点文件")
        
        logger.info(f"🎉 处理完成！")
        logger.info(f"  - 索引文件: {FAISS_INDEX_PATH}")
        logger.info(f"  - 文本映射: {CHUNKS_MAPPING_PATH}")
        logger.info(f"  - 处理日志: processing_log.json")
        
    except KeyboardInterrupt:
        logger.info("👋 程序被用户中断")
    except Exception as e:
        logger.error(f"💥 程序执行出错: {e}", exc_info=True)
        processor._save_checkpoint()

if __name__ == "__main__":
    main()