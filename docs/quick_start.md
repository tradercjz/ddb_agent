# DDB-Agent 快速入门指南

欢迎使用 DDB-Agent！本指南将引导您完成项目的首次配置，让您能够在几分钟内启动并运行 Agent。

## 先决条件

在开始之前，请确保您的本地环境中已安装以下软件：

*   **Git**: 用于克隆项目代码。
*   **Python 3.10+**: Agent 的运行环境。
*   **DolphinDB**: 您需要一个正在运行的 DolphinDB 服务实例，Agent 将连接到此实例进行操作。

## Step 1: 获取项目代码

首先，使用 Git 将 DDB-Agent 的代码克隆到您的本地计算机。打开终端并执行以下命令：

```bash
git clone https://github.com/tradercjz/ddb_agent.git
cd ddb-agent
```

## Step 2: 安装依赖

项目的所有依赖项都已在 `requirements.txt` 文件中列出。我们强烈建议您在一个 Python 虚拟环境中进行安装，以避免与系统中的其他库产生冲突。

```bash
# (可选，但推荐) 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate  # 在 Windows 上使用 `venv\Scripts\activate`

# 安装所有必需的库
pip install -r requirements.txt
```

## Step 3: 配置环境变量 (`.env` 文件)

这是整个配置过程中**最核心**的一步。Agent 的所有敏感信息和环境配置（如 API 密钥、数据库密码）都通过 `.env` 文件进行管理。这样做可以确保您的机密信息不会被硬编码到代码中，也方便在不同环境间迁移。

1.  **创建 `.env` 文件**:
    项目提供了一个模板文件 `.env.example`。您只需将其复制一份并重命名为 `.env` 即可。
    ```bash
    cp .env.example .env
    ```

2.  **编辑 `.env` 文件**:
    用您喜欢的文本编辑器打开刚刚创建的 `.env` 文件，并根据下面的说明填写您的配置信息。

### `.env` 文件详解

这是一个完整的 `.env` 文件示例，下面将对每个配置项进行详细说明。

```env
# =======================================================
# DolphinDB Connection Configuration (Required)
# =======================================================
# 您的 DolphinDB 服务器的主机名或 IP 地址
DDB_HOST="127.0.0.1"
# 您的 DolphinDB 服务器的端口号
DDB_PORT="8848"
# 用于登录 DolphinDB 的用户名
DDB_USER="admin"
# 用于登录 DolphinDB 的密码
DDB_PASSWORD="123456"

# =======================================================
# Large Language Model (LLM) Configuration (Required)
# =======================================================
# 您的大语言模型提供商的 API 密钥
# 这是项目能够“思考”的关键，请务必填写
LLM_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 您的大语言模型提供商的 API 基础 URL
# 对于 DeepSeek, 通常是 https://api.deepseek.com
# 对于 OpenAI, 通常是 https://api.openai.com/v1
LLM_BASE_URL="https://api.deepseek.com"

LLM_MODEL="deepseek-chat"

# =======================================================
# Optional Tool Configuration
# =======================================================
# (可选) 百度千帆AI搜索的 Token，用于启用 Web 搜索工具
# 如果您不需要网页搜索功能，可以留空或删除此行
BAIDU_QIANFAN_TOKEN="your_baidu_qianfan_token"
```

#### **DolphinDB 连接配置 (核心)**

这组配置项让 Agent 能够连接到您的 DolphinDB 数据库并执行脚本。

*   `DDB_HOST`: DolphinDB 服务器的 IP 地址或主机名。如果是本地运行，通常是 `127.0.0.1`。
*   `DDB_PORT`: DolphinDB 服务器的端口。默认端口通常是 `8848`。
*   `DDB_USER`: 登录 DolphinDB 的用户名。默认是 `admin`。
*   `DDB_PASSWORD`: 对应用户的密码。默认是 `123456`。

#### **大语言模型 (LLM) 配置 (核心)**

这组配置项让 Agent 能够调用 AI 模型进行思考、规划和生成代码。

*   `LLM_API_KEY`: **[必需]** 您的 LLM 服务提供商的 API 密钥。这是一个敏感信息，请妥善保管。
*   `LLM_BASE_URL`: **[必需]** LLM 服务的 API 端点。请确保其与您使用的模型服务商匹配。
*   `LLM_MODEL`: 指定 Agent 默认使用的模型。这个名称应该与 `models.json` 文件中定义的某个模型 `name` 相匹配。`deepseek-chat` 是一个不错的默认选择。

#### **可选工具配置**

这部分用于配置 Agent 可能使用的、需要额外认证的外部工具。

*   `BAIDU_QIANFAN_TOKEN`: 如果您需要 Agent 具备网页搜索能力（例如，查询最新的财经新闻），则需要在此处配置百度千帆的 Token。如果不需要，**此项可留空**。

> **重要提示**: `.env` 文件包含了您的机密信息。请**不要**将此文件提交到任何 Git 仓库中。项目已在 `.gitignore` 文件中默认忽略了它。


## Step 4: 下载dolphindb文档

在项目根目录下执行：

```bash
git clone https://github.com/tradercjz/documentation.git
```

下载文档到本地，之后可以构建索引，以及基于文档来进行RAG问答


## Step 5: 构建知识库索引

* 这个构建过程可以跳过，实际项目里已经带上了提前构建好的索引

为了让 Agent 能够回答与您的项目（例如，`documentation` 目录下的文档）相关的问题，您需要为这些文档构建一个向量索引。这个过程是 RAG (检索增强生成) 功能的核心。

在项目根目录下执行：

```bash
python build_index.py
```

该命令会扫描 `documentation` 目录下的所有 `.md` 文件，通过 LLM 为它们创建摘要和关键词，并生成一个索引文件保存在 `.ddb_agent/file_index.json`。



## Step 6: 启动 Agent！

恭喜您，所有配置均已完成！现在可以启动 DDB-Agent 的终端交互界面了。

```bash
python main.py
```

您将看到一个欢迎界面。现在，您可以开始通过输入命令（如 `/help`）或直接提问来与您的专属 DolphinDB 助手进行交互了。

如果需要RAG问答，则输入 /chat 问题 进行交互

如果是需要进行数据分析，则输入 /sql 进入数据分析模式，此时可以/use dfs://xx 将dolphindb的数据库加载到对话上下文里。

### 下一步？

尝试一下我们的核心功能：[交互式数据分析工作流](./dataAnalysis.md)，体验与 AI 协作分析数据的全新方式！