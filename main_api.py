from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
import json
from typing import List, Dict, Any

from agent.agent import DDBAgent
from services.agent_service import AgentService
from mcp.market.market_manager import MCPMarketManager
from mcp.server.server_manager import MCPServerManager
from fastapi.middleware.cors import CORSMiddleware


class ReactTaskRequest(BaseModel):
    conversation_history: List[Dict[str, Any]]

class ChatTaskRequest(BaseModel):
    conversation_history: List[Dict[str, Any]]
    task_type: str = "chat"

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("INFO:     Starting up DDB-Agent Service...")
    
    # 1. 初始化核心引擎
    mcp_market_manager = MCPMarketManager()
    mcp_server_manager = MCPServerManager(market_manager=mcp_market_manager)
    agent_core = DDBAgent(
        project_path=".", 
        model_name="gpt-oss-120b", 
        max_window_size=128000,
        mcp_market_manager=mcp_market_manager,
        mcp_server_manager=mcp_server_manager,
        enable_mcp=True # 显式启用
    )
    
    # 2. 初始化服务层，并注入核心引擎
    app.state.agent_service = AgentService(agent=agent_core)
    
    print("INFO:     DDB-Agent Service has started successfully.")

    # ---- Lifespan 的核心：yield 一次，应用会在这里运行 ----
    yield
    # --------------------------------------------------

    # --- 这是应用关闭时执行的代码 ---
    print("INFO:     Shutting down DDB-Agent Service...")
    # 在这里可以添加清理逻辑，例如：
    # if hasattr(app.state.agent_service.agent, 'mcp_server_manager'):
    #     await app.state.agent_service.agent.mcp_server_manager.stop_all_servers()
    print("INFO:     DDB-Agent Service has been shut down.")


# --- FastAPI应用实例 ---
# 将 lifespan 函数传递给 FastAPI 的构造函数
app = FastAPI(title="DDB-Agent API", lifespan=lifespan)
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,              # 允许访问的源
    allow_credentials=True,             # 允许携带cookies
    allow_methods=["*"],                # 允许所有方法 (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],                # 允许所有请求头
)

@app.post("/api/v1/tasks/react/stream")
async def stream_react_task(request_body: ReactTaskRequest, request: Request):
    agent_service: AgentService = request.app.state.agent_service
    event_generator = agent_service.handle_react_request(request_body.conversation_history)

    async def sse_generator():
        async for event_data in event_generator:
            if await request.is_disconnected():
                break
            yield {"event": "status_update", "data": json.dumps(event_data)}
        yield {"event": "close", "data": "Stream closed"}

    return EventSourceResponse(sse_generator())

@app.post("/api/v1/tasks/chat/stream")
async def stream_chat_task(request_body: ChatTaskRequest, request: Request):
    print("requst_body:", request_body)
    agent_service: AgentService = request.app.state.agent_service
    event_generator = agent_service.handle_chat_request(
        request_body.conversation_history
    )

    async def sse_generator():
        async for event_data in event_generator:
            if await request.is_disconnected():
                break
            yield {"event": "status_update", "data": json.dumps(event_data)}
        yield {"event": "close", "data": "Stream closed"}

    return EventSourceResponse(sse_generator())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_api:app", host="192.168.0.174", port=8000, reload=True)