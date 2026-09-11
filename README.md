# Agent Marketplace

已实现 Agent 发布与发现、任务发布、竞价排序、预算内选标、支付、交付、下载和已完成任务评价。

前端使用 React + TypeScript；独立后端使用 FastAPI + SQLAlchemy；Docker Compose 使用 PostgreSQL 16。AWS 配置将业务编排器和竞价／交付 Agent 分别部署在两个 Amazon Bedrock AgentCore Runtime 中。支付复用**现有 AgentCore Payments 绑定的 Stripe/Privy 钱包**，使用 x402 v2 和 Base Sepolia USDC，不创建新钱包。

**AWS 登录入口：https://dp7428wrh61ns.cloudfront.net/login**。部署于 `us-east-1`，详见 [已部署环境与验证记录](docs/deployed-environment.md)。账号由管理员创建，Cognito 自助注册已关闭；已有账户可正常登录和找回密码。

独立演示账户为 **`demo@agentmarketplace.example`**，密码单独提供。可浏览 **11 个 Agent**，查看共享的 **5 个历史测试任务、3 笔历史测试支付记录**及交付物。共享任务只读；演示账户可创建自己的任务、体验免费 Agent，或授权自动选择付费 Agent，并通过已绑定的 Connector3 Stripe/Privy 测试钱包付款和执行。

AWS 用户登录后可直接使用本地默认的 **8 个演示 Agent**，支持搜索、分类、竞价和交付。点击 **Try agent**，或通过 **Post a task → Post task & get bids → Choose demo agent → Run demo** 体验完整流程。交付内容由 Bedrock 生成，可下载并留下个人反馈；演示无需钱包、不扣款，不影响公开付费信誉。个人任务、支付记录和已发布 Agent 按账户独立保存。使用 `scripts/seed_aws.py` 可重复初始化这份共享目录。

任务支持 **I'll choose an agent / Automatic: bid, pay & run** 两种模式，也可筛选免费演示或付费 Agent。自动模式在发布时授权任务预算内的支付，后台完成竞价、选标、AgentCore Payments 支付和交付，关闭网页后继续执行。选标要求至少 70% 匹配、报价在预算内，再按 `quality × match / price` 排序。手动模式仍需逐步确认；旧任务可点击 **Run automatically** 授权剩余步骤。详见 [自动竞价与选标](docs/bidding-and-selection.md)。

AWS Agent 通过 **AgentCore Web Search** 实际搜索、读取网页，通过 **AgentCore Code Interpreter** 执行计算、数据处理、代码测试和流程规则，并保存可下载文件。任务详情展示 **Execution evidence**、来源时间、工具输入输出和验收检查；仅生成文本不能完成任务。缺少必要输入或外部系统连接时明确阻止执行。历史结果会标注缺少工具证据，可点击 **Run with real tools** 重新执行，复用已结算付款，不再次扣款。详见 [真实工具执行](docs/real-execution.md)。

提供 [Northstar 业务场景自动执行脚本](docs/business-scenarios.md)：发布 3 个业务 Agent 和经营分析、库存补货、客服分流任务，自动竞价和选标，执行总计不超过 **0.03 Base Sepolia 测试 USDC** 的支付，核对链上转账，再生成并保存交付物。

## 本地运行

需要 Docker 和 Docker Compose：

```bash
docker compose up --build -d
```

- 前端：http://localhost:3000
- API 文档：http://localhost:8001/docs
- 健康检查：http://localhost:8001/api/health
- PostgreSQL：`localhost:5433`，数据库／用户均为 `marketplace`

默认数据库密码仅用于本地开发。复制 `.env.example` 为 `.env` 后可修改密码和端口。数据库保存于 `marketplace_data` volume，重启容器不会丢失任务、订单和评价。

首次启动会执行 Alembic 迁移并创建 8 个英文演示 Agent。选择 **Automatic: bid, pay & run** 可体验后台完整流程；手动模式依次选标、授权支付和获取交付物。免费演示 Agent 不需要支付。

**本地是演示模式**：交付物为明确标注的模板，支付为模拟记账，不调用模型、不签名、不转移真实 USDC，不生成虚假的链上交易哈希。统计和信誉从实际数据库记录计算，初始值为零。

## 开发运行

API 可使用本地 SQLite；上线必须使用 PostgreSQL：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cd backend
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

直接开发时，另开终端在 `backend/` 下运行 `../.venv/bin/python -m app.worker`，使用同一数据库处理自动任务。Docker Compose 已包含后台 worker。

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

开发前端为 http://localhost:5174，通过 Vite 转发 `/api` 至 `8001`。独立托管前端时可在构建前设置 `VITE_API_URL`。

## 目录

```text
frontend/                  全英文 React 控制台、独立登录页、找回密码、Cognito
backend/app/main.py        REST API / JWT 验证 / 用户身份绑定
backend/app/runtime.py     AgentCore HTTP 入口：/invocations、/ping
backend/app/service.py     编排、竞价、预算、订单和信誉
backend/app/agents.py      本地 Agent 与 Bedrock Converse / Runtime 调用
backend/app/payments.py    AgentCore Payments 签名和 x402 facilitator 结算
backend/app/automation.py  自动任务授权、持久化队列、租约和分阶段执行
backend/app/worker.py      后台轮询队列，调用编排 Runtime
backend/migrations/        PostgreSQL / SQLite 数据库迁移
backend/tests/             业务、并发、隔离和 AWS API schema 测试
infra/                     AWS CDK：VPC、RDS、ECS API、双 Runtime、Cognito、CloudFront
contracts/                 AgentRegistry、TaskEmitter、Reputation 合约及测试
scripts/migrate_aws.py     在 AWS VPC 内执行数据库迁移
scripts/seed_aws.py        初始化 AWS 共享演示目录，不覆盖已有数据
scripts/check_payments.py  只读验证现有 Stripe/Privy 钱包、身份、状态和余额
scripts/bind_aws_wallet.py 将配置好的现有钱包绑定到指定 AWS 登录账户并验证
scripts/run_business_scenarios.py 自动发布业务场景、竞价、测试网支付和交付
scripts/aws_workspace_snapshot.py 通过私有 ECS 任务只读导出指定付款账户的数据
scripts/verify_deployment.py 只读检查公网入口、认证隔离和 AWS 部署资源
docs/                      架构、AWS 部署、运维说明
```

## 验证

```bash
# 后端测试（隔离的临时 SQLite）
.venv/bin/pytest -q backend/tests
.venv/bin/ruff check backend

# 真实 PostgreSQL 测试：只使用专用测试库，不碰业务库
docker compose exec db createdb -U marketplace marketplace_test
TEST_DATABASE_URL=postgresql+psycopg://marketplace:marketplace-local-only@127.0.0.1:5433/marketplace_test \
  .venv/bin/pytest -q backend/tests

# 前端构建和浏览器测试；先启动 docker compose
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e

# 合约编译和本地 EVM 测试
cd ../contracts
npm ci
npm run compile
npm test
```

## AWS 与链上部署

详见 [AWS 部署说明](docs/aws-deployment.md)、[架构与 PDF 对照](docs/architecture.md) 和 [运行维护](docs/operations.md)。

AWS 使用私有 S3 + CloudFront OAC 托管前端，ECS Fargate 分别托管 API 与后台 worker，RDS PostgreSQL 保存数据和自动任务队列，AgentCore Runtime 执行业务编排、支付和竞价／交付。`/login` 提供全英文邮箱登录、已有账户邮箱验证和密码重置，不提供自助注册。部署输出包含 `WebsiteUrl`、`LoginUrl` 和 `WorkflowWorkerServiceName`。

支付使用现有 PaymentManager `demopaymentmanager-zy4lsroxj3` 和 Connector3（`mystripeprivyconnector3-wbtiy89xwz`）。**演示账户 `demo@agentmarketplace.example` 已绑定并获授权使用现有 ACTIVE 的 Stripe/Privy 钱包，网络为 Base Sepolia 测试网**；登录后进入 **Payments → Stripe / Privy wallet** 查看地址和余额。`PAYMENT_OWNER_SUB` 指定原付款账户，`PAYMENT_DELEGATE_SUB` 指定获授权的演示账户，其累计付款与预留资金上限为 **1 测试 USDC**。两个账户共用钱包资金，任务和付款账本按登录账户分别保存；共享历史测试任务只读，其他账户不会自动获得钱包权限。资源标识和验证记录见 [已部署环境](docs/deployed-environment.md)。

三份合约提供源码、编译、部署脚本及本地 EVM 测试。**当前网页的注册、任务与信誉以数据库为准，尚未连接链上事件同步**。云端 USDC 支付结算与这三份目录合约独立，因此不依赖目录合约部署。该边界也显示在英文 Settings 页面中。
