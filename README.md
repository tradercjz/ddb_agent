# ddb_agent: An Intelligent RAG-based AI Agent for DolphinDB

**ddb_agent** 是一个专为 [DolphinDB](https://www.dolphindb.com/) 生态系统设计的、具备高级检索增强生成（RAG）能力的命令行 AI 代理。它不仅仅是一个聊天机器人，更是一个能深入理解你的项目代码库、并结合相关文件上下文为你提供精准回答的智能开发助手。

---

## 核心特性

-   **🧠 智能检索增强 (RAG)**: 在回答问题前，能自动从项目文件中检索最相关的内容作为上下文，提供有理有据的回答。
-   **📚 智能上下文管理**: 独创的预算分配和剪枝策略，能够处理超长对话历史和巨大的代码文件，有效避免超出模型 Token 限制。
-   **✨ 优雅的命令行界面**: 基于 `rich` 和 `prompt-toolkit` 构建，支持多行输入、历史记录、自动建议和流式 Markdown 输出，提供极致的交互体验。
-   **🚀 声明式 LLM 调用**: 创新的 `@llm.prompt` 装饰器，将函数和文档字符串优雅地转换为 LLM API 调用，让代码更简洁、易读。
-   **🧩 模块化与可扩展架构**: 项目采用高内聚、低耦合的模块化设计，无论是 RAG 策略、上下文剪枝器还是 LLM 模型，都易于替换和扩展。
-   **💾 会话持久化**: 能够自动保存和加载对话历史，支持多轮对话和上下文记忆。

---

## 架构概览

本代理采用分层模块化架构，各组件职责分明，协同工作。

```mermaid
graph TD
    subgraph "User Interface (main.py)"
        CLI
    end

    subgraph "Core Orchestrator (agent.py)"
        Agent[DDBAgent]
    end

    subgraph "Core Components"
        RAG[RAG System<br>(rag/)]
        Context[Context Management<br>(context/)]
        LLM[LLM Interface<br>(llm/)]
        Session[Session Manager<br>(session/)]
    end

    CLI -- User Input --> Agent
    Agent -- 1. Retrieve Context --> RAG
    Agent -- 2. Build Prompt --> Context
    Agent -- 3. Call Model --> LLM
    Agent -- 4. Manage History --> Session
    LLM -- Response --> Agent
    Agent -- Formatted Output --> CLI
```

---

## 安装与配置

请按照以下步骤来设置和运行本项目。

### 1. 克隆项目

```bash
git clone <your-repository-url>
cd ddb_agent
```

### 2. 创建并激活虚拟环境

建议使用虚拟环境以隔离项目依赖。

```bash
# For Unix/macOS
python3 -m venv venv
source venv/bin/activate

# For Windows
python -m venv venv
.\venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置模型和 API 密钥

配置分为两步：定义模型和设置凭据。

#### a) 定义模型 (`models.json`)

在项目根目录创建一个 `models.json` 文件。这里定义了你可以使用的不同 LLM 的别名和配置。

```json
[
  {
    "name": "deepseek-chat",
    "model_name": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "api_key_env_var": "DEEPSEEK_API_KEY",
    "description": "Default chat model from DeepSeek.",
    "log_requests": true
  },
  {
    "name": "openai-gpt4o",
    "model_name": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_key_env_var": "OPENAI_API_KEY",
    "description": "OpenAI's GPT-4o model.",
    "log_requests": false
  }
]
```

#### b) 设置凭据 (`.env` 文件)

在项目根目录创建一个 `.env` 文件来安全地存放你的 API 密钥。**不要将此文件提交到 Git 仓库**。

```dotenv
# .env file
# Keys should match the "api_key_env_var" values in models.json

DEEPSEEK_API_KEY="sk-your-deepseek-api-key"
OPENAI_API_KEY="sk-your-openai-api-key"
```

---

## 使用方法

使用本代理分为两步：首先为你的项目构建知识库索引，然后启动代理进行交互。

### 步骤 1: 构建知识库索引

Agent 需要一个索引文件来了解你的项目。运行以下脚本来生成它。

```bash
python build_index.py
```

该脚本会扫描 `documentation` 目录（可在 `build_index.py` 中修改路径）下的所有文件，使用 LLM 为其创建摘要和关键词，并生成一个索引文件（默认为 `.ddb_agent/file_index.json`）。

**注意**: 这个步骤只需要在项目文件发生显著变化时重新运行。

### 步骤 2: 启动代理

运行 `main.py` 启动交互式命令行界面。

```bash
python main.py
```

现在你可以开始和 ddb_agent 对话了！

### 可用命令

在代理的提示符后，除了直接提问，你还可以使用以下命令：

| 命令                | 描述                       |
| ------------------- | -------------------------- |
| `/new` 或 `/reset`  | 开始一个全新的对话会话。   |
| `/help`             | 显示此帮助信息。           |
| `/exit` 或 `/quit`  | 退出代理程序。             |

---

## 路线图：演进为真正的 Coding Agent

本项目不仅仅是一个问答系统，它的架构为演进成一个能**编写、执行、调试**代码的自主代理奠定了基础。

-   **Phase 1: 实现核心“执行-反思”循环**
    -   [ ] **代码执行器**: 开发一个能安全执行 DolphinDB 脚本并捕获结果/错误的组件。
    -   [ ] **自我修正能力**: 让 Agent 在代码执行失败时，能结合错误信息和 RAG 上下文，自动进行调试和代码修复。

-   **Phase 2: 引入规划与工具使用能力**
    -   [ ] **任务规划器**: 对于复杂任务，让 Agent 先生成一个多步骤的行动计划。
    -   [ ] **工具抽象**: 将“执行 DolphinDB 脚本”、“执行 Python 代码”、“读写文件”等能力抽象为 Agent 可以调用的“工具”。

-   **Phase 3: 迈向自主与环境感知**
    -   [ ] **运行时文件感知**: 监控文件系统变化，当依赖的代码在任务执行中被修改时，Agent 能够感知并做出反应。
    -   [ ] **应用级交互 (A2A)**: 将 Agent 封装成一个服务，提供 API 或 CLI 接口，使其能被其他程序或自动化流程调用。

---

## 贡献

欢迎任何形式的贡献！如果你有好的想法或发现了 Bug，请随时提交 Pull Request 或创建 Issue。

1.  Fork 本仓库
2.  创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3.  提交你的修改 (`git commit -m 'Add some AmazingFeature'`)
4.  推送到分支 (`git push origin feature/AmazingFeature`)
5.  打开一个 Pull Request

---

## 许可证

本项目基于 [MIT 许可证](LICENSE) 发布。