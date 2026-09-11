# AWS 部署

本仓库使用 AWS CDK v2 管理部署。默认区域为 `us-east-1`，应用栈为 `AgentMarketplace`。部署输出保存到 `artifacts/aws-outputs.json`；真实支付仅在现有钱包资源和付款账户配置完整后启用。

## 先决条件

1. 具备部署 VPC、RDS、ECS、ECR、CloudFront、Cognito、IAM 和 AgentCore Runtime 权限的 AWS 账户。
2. 选择支持 AgentCore Runtime 和 Payments 的区域；本项目使用现有 PaymentManager 所在的 `us-east-1`。
3. 已有 AgentCore **PaymentManager**、类型为 **StripePrivy** 且 READY 的 **PaymentConnector**、ACTIVE 的 **PaymentInstrument**，知道该钱包原有的 AgentCore `userId`。
4. 现有 Stripe/Privy 钱包已与 AgentCore 绑定；本项目不创建、不迁移钱包或供应商凭据。不要把钱包私钥放进前端。
5. 已取得所选 Amazon Bedrock 模型／inference profile 的调用权限。
6. Docker、Node.js 22、Python 3.12 和 AWS CLI，已配置 AWS 凭证；非 ARM 主机需要能构建 `linux/arm64` 镜像。

支付服务的真实 API schema 已按 boto3 `1.43.92` 验证。若使用不同版本，先确认 SDK 暴露 `get_payment_instrument`、`get_payment_instrument_balance`、`create_payment_session` 和 `process_payment`。

GitHub Actions 使用 `infra/cdk.context.ci.json` 中的测试账户及查询结果执行 `cdk synth --no-lookups`，无需 AWS 凭据。该文件仅用于 CI；正常部署由 CDK 查询实际账户配置，生成的 `infra/cdk.context.json` 不提交到 Git。

先用只读脚本确认现有资源（不会签名、不会创建钱包、不会付款）：

```bash
.venv/bin/python scripts/check_payments.py \
  --region us-east-1 \
  --manager-arn "$PAYMENT_MANAGER_ARN" \
  --instrument-id "$PAYMENT_INSTRUMENT_ID" \
  --user-id "$PAYMENT_USER_ID"
```

Connector ID 可以不传，脚本会从现有 instrument 查询。若已知，增加 `--connector-id "$PAYMENT_CONNECTOR_ID"`。

## 部署资源

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1

cd frontend
npm ci
npm run build

cd ../infra
npm ci
npm run synth
npx cdk bootstrap
npx cdk deploy \
  --outputs-file ../artifacts/aws-outputs.json \
  --parameters PaymentManagerArn="$PAYMENT_MANAGER_ARN" \
  --parameters PaymentConnectorId="$PAYMENT_CONNECTOR_ID" \
  --parameters PaymentInstrumentId="$PAYMENT_INSTRUMENT_ID" \
  --parameters PaymentUserId="$PAYMENT_USER_ID" \
  --parameters FacilitatorUrl="https://x402.org/facilitator"
```

这些标识均使用现有钱包资源。可先只提供 `PaymentManagerArn` 部署网站；其余支付参数默认空，钱包绑定和真实支付保持禁用。登录后获取自己 `/api/me` 返回的 `id`，再次部署并增加 `--parameters PaymentOwnerSub="<你的 Cognito sub>"`，同时配置原有 PaymentInstrument ID 和 payment userId。如果已有用于钱包管理的 Privy 前端，可同时传 `--parameters PrivyWalletUrl="https://..."`。

部署包含：

- S3 私有前端资源和 CloudFront HTTPS，使用 OAC + SigV4 授权访问；S3 阻止全部公开访问。
- CloudFront VPC Origin 到内部 ALB，API 不暴露公网负载均衡器；公网使用 HTTPS，VPC 内使用明确配置的 HTTP/80，ALB 仅接受 CloudFront 托管前缀列表来源。
- 独立 FastAPI API，运行在 ARM64 ECS Fargate。
- 两个 ARM64 AgentCore Runtime：编排器在 VPC 内；竞价／交付 Runtime 使用 Bedrock。
- RDS PostgreSQL，位于隔离子网，加密、7 天备份、删除保护。
- Secrets Manager 保存 RDS 凭证，应用只接收 secret ARN。
- Cognito 用户池、无客户端密钥的 Web Client；关闭自助注册，由管理员创建账户。独立英文登录页支持邮箱密码登录、已有账户验证码确认、密码重置，以及托管 Authorization Code + PKCE 登录。
- 按调用关系分离的 API、编排器、竞价器 IAM 角色。

模板将创建收费资源，包括 RDS、NAT Gateway、ALB 和 ECS。未配置多实例 API、高可用 RDS 或自动伸缩；可以在 `infra/app.ts` 中按工作负载扩展。

## 初始化数据库

更新已有部署、增加兼容字段时，先用当前 ECS 镜像运行新增迁移，再部署新应用。例如本次选标功能：

```bash
.venv/bin/python scripts/migrate_aws.py --region us-east-1 \
  --include-migration backend/migrations/versions/0003_task_selection.py
```

该选项只将指定的本地迁移文件复制进一次性任务，不改写已有迁移。`0003` 为旧任务设置 `manual` / `all` 默认值，不删除业务数据。新增字段就绪后再更新 Runtime 和 ECS，可以避免部署切换期间读取缺失字段。

AWS 模式不会自动建表或创建演示账户，部署后运行：

```bash
cd ..
.venv/bin/python scripts/migrate_aws.py --region us-east-1
.venv/bin/python scripts/seed_aws.py --region us-east-1
```

脚本通过 ECS 在 VPC 内执行 `alembic upgrade head`，确认容器退出码。然后打开 stack output 中的 `LoginUrl`（`WebsiteUrl/login`），使用管理员提供的 Cognito 账户登录。CloudFront Function 将 `/login` 路径路由到 S3 的应用入口。

CDK 设置 `selfSignUpEnabled: false`，对应 Cognito `AllowAdminCreateUserOnly: true`；新增账户仅允许管理员创建。已有未验证账户仍可完成邮箱验证。密码至少 12 位并包含大小写字母、数字和符号。密码直接通过 HTTPS 提交 Cognito，不经过应用 API、不写入数据库或浏览器存储。访问令牌仅保存在当前标签页的 sessionStorage，1 小时过期后重新登录。API 校验 Cognito 签名、issuer、client ID、有效期和 access token 类型。

为独立演示账户开放已有测试数据时，设置 `ShowcaseUserSub` 为其 Cognito subject，`ShowcaseTaskIds`、`ShowcaseAgentIds` 为逗号分隔的明确资源 ID。只读授权在后端按已验证的登录身份判断；共享任务的所有修改接口返回 `403`，其他账户仍受原有隔离规则约束。该配置不迁移记录，也不会赋予 `PaymentOwnerSub` 的钱包权限。

通过 `scripts/verify_demo_user.py --credentials-file <私有凭据文件>` 和 `node scripts/verify_demo_browser.mjs <私有凭据文件>` 可验证实际登录、共享范围、只读限制、桌面／手机展示和下载。凭据文件包含 `email`、`password`、`sub`，应限制本机读取权限，不能提交到仓库；验证报告不包含密码或令牌。

部署完成后执行只读检查（不创建账户、不发送邮件、不付款）：

```bash
.venv/bin/python scripts/verify_deployment.py --region us-east-1
```

检查公网登录入口、Cognito 自助注册已关闭、API 健康与匿名拒绝、S3 OAC、私有 ECS／RDS 和两个 Runtime 状态，报告保存到 `artifacts/aws-verification.json`。

`seed_aws.py` 将本地默认的 8 个 Agent 作为共享演示目录写入 RDS，新用户登录后即可浏览、搜索和运行。初始化可以重复执行，不覆盖已有记录。演示资料由独立系统身份持有，不属于任何登录用户；卡片标注 **Demo**。演示 Agent 可参与竞价和选标，选择后点击 **Run demo** 生成交付物，无需绑定钱包。示例价格不会用于扣款，服务端拒绝演示任务调用付款接口，演示反馈不计入公开付费信誉。

若需接受付费任务，发布真实专业 profile 并配置有效收款钱包。演示与付费 Agent 都在共享竞价 Runtime 中运行，付费 Agent 必须完成支付后才能交付。任务相关的生成结果由 Bedrock 实际推理获得，但未接入实时行情、Bloomberg、浏览器或外部数据检索工具。

## 连接现有 Stripe/Privy 钱包并测试支付

1. 使用 `PaymentOwnerSub` 指定的账户登录，进入 **Payments → Connect existing wallet**。
2. 后端调用 `GetPaymentInstrument` 和 `GetPaymentConnector` 验证已有 Stripe/Privy 钱包、归属 userId 和状态，再查询 Base Sepolia USDC 余额并写入账户绑定。
3. 已有签名授权继续使用；若已过期或撤销，前往你现有的 Privy 管理页面重新授权。
4. 如需测试资金，使用 [Circle Faucet](https://faucet.circle.com/) 为同一钱包地址的 Base Sepolia 网络充值测试 USDC。
5. 发布任务、比较报价、选择中标者并点击 **Pay & authorize**。
6. 服务端创建带任务预算的支付 session，执行 `ProcessPayment`，再向 facilitator `/verify`、`/settle` 提交证明。
7. 成功后可以在支付列表查看真实 Base Sepolia 交易链接并开始交付。

管理员也可在支付参数部署完成、指定账户已登录过网站后执行绑定：

```bash
.venv/bin/python scripts/bind_aws_wallet.py --region us-east-1
```

脚本读取 CloudFormation 中的现有 instrument、payment userId、connector 和 `PaymentOwnerSub`，核对 Cognito 账户后，在私有 ECS 任务中调用应用的绑定逻辑。它将映射写入 RDS，再通过新的数据库连接和账户／钱包 API 处理函数验证持久化、状态及余额；结果保存到 `artifacts/aws-wallet-binding.json`。重复运行同一绑定不会新增绑定事件，发现不同的已绑定钱包则拒绝替换。该操作不创建钱包、不支付，不修改消费预算或支付记录。

默认 facilitator 需在目标环境确认支持 x402 v2、`eip155:84532` 和 USDC exact scheme。若供应商需要认证，配置 `FACILITATOR_TOKEN`；CDK 当前不直接注入该可选 token，可通过 Secrets Manager 扩展 Runtime secret 加载。不要将认证值传到网页。

钱包管理链接优先使用你配置的 `PrivyWalletUrl`，其次使用 instrument 内嵌 wallet 的 `redirectUrl`。未提供时仍可查询余额和付款，但网页不会猜测或创建钱包管理链接。`ACTIVE` 不代表所有签名授权始终有效；实际授权由 AgentCore / Privy 在付款时检查。

## AgentCore 容器协议

运行时容器：

```bash
docker build --platform linux/arm64 \
  -f backend/Dockerfile.runtime -t agent-marketplace-runtime backend
```

- 监听 `0.0.0.0:8080`。
- `GET /ping` 返回 `{"status":"Healthy"}`。
- `POST /invocations` 接收 JSON。
- API → orchestrator、orchestrator → bidders 通过 `boto3.invoke_agent_runtime` + SigV4。
- 每次调用使用新的 UUID session ID，避免同一 Runtime session 上的并发请求冲突。
- 支付 session 与 Runtime session 分开持久化，不能互换。
- Runtime 文件系统不用于存储业务数据。

## 合约部署（可选，独立于网页）

```bash
cd contracts
npm ci
npm run compile

# 在本地环境中安全设置 BASE_SEPOLIA_RPC_URL 和 DEPLOYER_PRIVATE_KEY。
# 使用仅持有测试 ETH 的部署钱包。
npm run deploy:sepolia
```

部署脚本强制 chain ID 为 `84532`，输出三个地址并写入 `deployment.sepolia.json`。**这一步不会自动让网页切换到链上目录**：当前版本还没有浏览器钱包签名、链上任务 ID 映射、事件 indexer 和信誉同步。

## 官方参考

- [AgentCore HTTP runtime contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)
- [AgentCore Payments overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments.html)
- [Create a payment session](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-session.html)
- [Process a payment / x402 schemas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-process-payment.html)
- [Fund wallets and grant permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-fund-wallet.html)
