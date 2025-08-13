import asyncio
import json
from typing import List, Dict, Any, AsyncGenerator, Union

from agent.agent import DDBAgent, FinalMessage
from agent.task_status import AnyTaskStatus
from rag.rag_status import AnyRagStatus
import queue 
from pydantic import BaseModel
from dataclasses import is_dataclass, asdict
from llm.llm_client import StreamChunk 


class AgentService:
    def __init__(self, agent: DDBAgent):
        self.agent = agent

    def _run_sync_generator_in_thread(
        self,
        task_generator,
        q: queue.Queue
    ):
        """
        这个函数将在一个单独的线程中运行。
        它会完全耗尽同步生成器，并将所有 yield 的值放入队列。
        """
        try:
            for item in task_generator:
                q.put(item)
        except Exception as e:
            # 将异常也放入队列，以便主线程可以捕获它
            q.put(e)
        finally:
            # 发送一个特殊的哨兵值，表示生成器已结束
            q.put(None)

    async def _process_queue_to_generator(
        self,
        q: queue.Queue
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        一个可复用的辅助函数，用于将队列中的项转换为可序列化的字典。
        """
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            
            if item is None:
                break
                
            if isinstance(item, Exception):
                import traceback
                yield {
                    "subtype": "error",
                    "message": str(item),
                    "error_details": traceback.format_exc()
                }
                break
            
            # --- 核心修改在这里 ---
            if isinstance(item, BaseModel):
                # 如果是 Pydantic 模型，使用 model_dump
                yield item.model_dump(mode='json')
            elif is_dataclass(item) and not isinstance(item, type):
                # 如果是 dataclass 实例，使用 asdict
                yield asdict(item)
            elif isinstance(item, dict):
                # 如果本身就是字典，直接 yield
                yield item
            else:
                # 后备方案，对于未知类型，记录一个警告并尝试转换
                print(f"Warning: Unknown item type in generator queue: {type(item)}. Converting to string.")
                yield {"type": "unknown", "data": str(item)}

    async def handle_chat_request(
        self,
        conversation_history: List[Dict[str, Any]]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        (修改后) 使用队列在线程和事件循环之间安全地传递数据。
        """
        loop = asyncio.get_running_loop()
        q = queue.Queue()
        task_generator = self.agent.run_chat_task(conversation_history)
        loop.run_in_executor(None, self._run_sync_generator_in_thread, task_generator, q)
        
        # 使用可复用的处理逻辑
        async for processed_item in self._process_queue_to_generator(q):
            yield processed_item


    # handle_react_request 也应该进行同样的改造
    async def handle_react_request(
        self,
        conversation_history: List[Dict[str, Any]]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        loop = asyncio.get_running_loop()
        q = queue.Queue()
        task_generator = self.agent.run_react_task(conversation_history)
        loop.run_in_executor(None, self._run_sync_generator_in_thread, task_generator, q)
        
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            
            if item is None:
                break
                
            if isinstance(item, Exception):
                import traceback
                yield {
                    "subtype": "error",
                    "message": str(item),
                    "error_details": traceback.format_exc()
                }
                break

            yield item.model_dump(mode='json')