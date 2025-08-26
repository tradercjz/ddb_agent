
# 按需云端 DolphinDB 环境

`ddb-agent` 现已集成强大的平台即服务（PaaS）功能，允许您直接通过命令行创建、管理并连接到临时的、按需分配的云端 DolphinDB 环境。

这项功能彻底解决了用户本地环境配置的难题。现在，您无需在本地安装 DolphinDB，即可在几分钟内获得一个配置完善、预装了示例数据的云端沙箱环境，是您测试、开发和学习的绝佳工具。

## 快速入门

只需五条命令，即可体验完整的云端工作流：

```bash
# 1. 登录 DolphinDB 云服务
/cloud login <您的用户名> <您的密码>

# 2. 创建一个新的云环境（例如，2核CPU，4GB内存）
/cloud vms create 2c4g

# 3. 列出您的云环境，获取其ID（请等待 STATUS 变为 RUNNING）
/cloud vms list

# 4. 将 Agent 的当前连接切换到新建的云实例
/ddbserver switch <从列表中获取的环境ID>

# 5. 开始工作 /sql 命令都将在您的云数据库上执行
/sql 你的问题 
```

## `/cloud` 命令详解

`/cloud` 命令是您管理云资源生命周期的控制面板。

### `1. /cloud login <用户名> <密码>`

这是您与云服务交互前必须运行的第一个命令，用于身份验证。

*   **用法**: `/cloud login myuser mysecretpassword`
*   **说明**: 该命令会将您的凭证发送至后端服务，并获取一个认证令牌（Token）。Agent 会将此令牌安全地存储在本地，用于后续所有 `/cloud` 和 `/ddbserver` 命令的认证。您只需登录一次，即可在会话期间保持登录状态，直到执行登出命令。

### `2. /cloud vms`

该命令用于管理您的虚拟机（VMs），这些虚拟机实际上是轻量级的容器实例。它包含三个主要操作：`list`（列出）、`create`（创建）和 `delete`（删除）。

#### `a. /cloud vms list` (默认操作)

列出您当前拥有的所有云环境。

*   **用法**: `/cloud vms list` 或直接输入 `/cloud vms`
*   **输出**: 一个清晰的表格，包含以下信息：
    *   **名称 (ID)**: 您环境的唯一标识符，后续操作将使用此ID。
    *   **状态 (Status)**: 环境的当前状态（`PENDING` - 待处理, `PROVISIONING` - 配置中, `RUNNING` - 运行中, `ERROR` - 错误, `DELETING` - 删除中）。
    *   **IP 地址 & 端口**: 连接信息，一旦状态变为 `RUNNING` 即可用。
    *   **规格 (Specs)**: 分配的 CPU 和内存资源。

#### `b. /cloud vms create [规格]`

创建一个新的、隔离的 DolphinDB 云环境。

*   **用法**:
    *   `/cloud vms create` (使用默认规格创建一个实例，如 2c4g)
    *   `/cloud vms create 4c8g` (创建一个4核CPU、8GB内存的实例)
*   **过程**: 这是一个异步命令。Agent 会向您实时展示后台任务的进度，包括“正在配置实例”、“正在部署DolphinDB”、“正在恢复示例数据”等状态。整个过程通常需要2-3分钟。

#### `c. /cloud vms delete <环境ID>`

立即删除指定的云环境。

*   **用法**: `/cloud vms delete ddb-env-a1b2c3d4`
*   **说明**: 当您完成工作，希望在环境自动过期前提前释放资源时，请使用此命令。

### `3. /cloud logout`

将您从云服务中登出，并删除本地存储的认证令牌。

*   **用法**: `/cloud logout`

## `/ddbserver` 命令详解

该命令用于管理 Agent 当前连接的是哪个 DolphinDB 服务器。

### `1. /ddbserver status` (默认操作)

显示 Agent 当前激活的 DolphinDB 连接详情。

*   **用法**: `/ddbserver status` 或直接输入 `/ddbserver`
*   **输出**: 一个信息面板，清晰地告诉您当前连接的是**本地默认实例**（配置来源于您的 `.env` 文件）还是**远程云实例**。面板会显示当前生效的服务器地址（Host）、端口（Port）和用户名（User）。

### `2. /ddbserver switch <目标>`

切换 Agent 的活动数据库连接。这是让您在本地和云端环境之间自由切换的核心命令。

*   **可用的 `<目标>`**:
    *   `<环境ID>`: 从 `/cloud vms list` 命令中获取的一个**正在运行的**云环境ID。
    *   `local` 或 `default`: 切换回您在 `.env` 文件中配置的默认本地 DolphinDB 连接。

*   **典型工作流示例**:
    1.  开始时，检查当前连接: `/ddbserver status` -> (显示连接到**本地**服务器)
    2.  创建并等待云环境就绪: `/cloud vms create`
    3.  切换到云环境: `/ddbserver switch ddb-env-xyz`
    4.  验证切换是否成功: `/ddbserver status` -> (现在显示连接到**云实例的IP**)
    5.  在云端执行您的任务...
    6.  工作完成，切换回本地: `/ddbserver switch local`
    7.  再次验证: `/ddbserver status` -> (再次显示连接到**本地**服务器)

---
全新的云功能为您提供了前所未有的灵活性和便利性，确保您随时都能拥有一个干净、可靠的 DolphinDB 环境来完成您的工作。

### 下一步？

尝试一下我们的核心功能：[交互式数据分析工作流](./dataAnalysis.md)，体验与 AI 协作分析数据的全新方式！

