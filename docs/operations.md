# 运行与维护

## 本地生命周期

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose stop
docker compose start
```

`docker compose down` 保留数据库 volume；不要在需要保留数据时使用 `down -v`。

本地演示模式故意采用共享用户，**不能作为多租户公网应用部署**。AWS 模式启用 Cognito 和 owner 过滤，拒绝使用 SQLite 作为持久数据库。

## 支付状态

| 状态 | 含义 | 处理 |
|---|---|---|
| `pending` / task `paying` | 已预留额度，流程进行中 | 等待；若进程终止，先核对外部交易 |
| `settled` | 有结算确认或明确标注的 demo receipt | 允许交付；重复 pay 不再次扣款 |
| `failed` | 签名前配置或创建 session 失败 | 额度已释放；修复配置后创建新任务 |
| `review_required` | 签名或结算结果不确定 | 额度保留，禁止重复支付和交付 |

**不要**把网络超时当作没有扣款，也不要直接把不确定订单重新置为待付款。

排查顺序：

1. 使用 payment ID、session ID 和 process ID 关联 CloudWatch 与供应商记录，日志中不要输出支付证明或私钥。
2. 核对 Base Sepolia 上交易 receipt、USDC token、金额、付款钱包、收款钱包、确认状态及授权 nonce。
3. 只在获得确定证据后，由数据库管理员在单个事务内调整 payment、task、用户 reserved／spent 和新增审计 event。
4. 已结算：只恢复为 `paid`，重试交付。未结算但签名仍有效：不能释放预留后重新支付，否则存在重复支出风险。

当前没有自动对账 worker、退款、争议仲裁或管理员支付修复 UI。PDF 的 TaskEmitter 不托管资金，本项目也没有 escrow。

2026-09-11 的 Northstar 场景使用了原支付的幂等 process 结果和签名完成对账；相关链上核验和事务更新记录保存在 `artifacts/business-scenarios/first-payment-*`、`second-payment-*`。这些记录针对该次已核实的支付，不能作为忽略其他 `review_required` 状态的依据。当前代码按 AWS 返回的 `paymentSession.paymentSessionId` 读取 session，并将原始签名放入 x402 v2 `paymentPayload.payload`，同时提供 `x402Version` 和 `accepted`。

## 模型与任务故障

- 竞价异常会回到 `open`，可以安全重新收集。
- 交付异常会回到 `paid`；共享演示任务回到 `demo_ready`。重试不重新付款。
- 如果进程在处理阶段被终止，任务可能停留在 `quoting` / `delivering`。确认对应 Runtime 调用已结束后，可分别恢复为 `open` / `paid`（共享演示交付恢复为 `demo_ready`）；恢复前检查是否已写入竞价或交付内容。
- API / CloudFront 超时时应先刷新任务状态。页面会轮询正在处理的任务，避免盲目重新发起支付。

对于长时间任务，后续应引入持久化队列、租约／心跳、失败重放和自动对账，再提高并发规模。

## 数据库

核心表：`users`、`agents`、`tasks`、`bids`、`payments`、`events`。

迁移 `0002` 增加现有 Stripe/Privy 钱包映射：登录用户 ID 与原有 payment userId 分别保存，历史订单保留 instrument / payer 快照。API IAM 只有读取现有钱包的权限，没有 `CreatePaymentInstrument` 权限。

迁移 `0003` 保存任务的 `selection_mode`、`agent_scope` 和 `selection_reason`。自动选标要求活跃、预算内且匹配度至少 70%，使用精确比例比较 `quality × match / price`；没有合格报价时保留 `bidding` 并记录原因。`auto-select` 与手动 `select` 共用条件更新，只有一次选择可以成功；自动选标不预留消费额度或调用付款接口。详见 [竞价与选标](bidding-and-selection.md)。

金额用整数 micros 存储。应用账户上限是**累计消费预算**，不是钱包余额；设置上限不充值钱包，也不为后续所有任务自动授权支付。

迁移状态：

```bash
docker compose exec backend alembic current
docker compose exec backend alembic check
```

修改模型时增加新迁移文件，不修改已上线的历史迁移。AWS 的 RDS secret 从 Secrets Manager 读取；应用缓存数据库连接，凭证轮换后应滚动重启 API 并发布新 Runtime 版本。

## 验证范围

测试覆盖：

- 完整发布、竞价、选标、支付、交付和评分。
- 同一任务并发支付不会生成第二笔订单。
- 不同任务同时支付不能超出同一账户预算。
- 报价上限、截止时间、付费 Agent 无支付不能交付、只有已完成任务可以评价。
- 手动/自动选标、Agent 池筛选、匹配度门槛、同分稳定排序、并发单一中标者和选标重试。
- 共享演示目录的竞价、选标、免钱包交付、下载和个人反馈；支付接口拒绝演示任务，演示不改变消费额度或公开信誉。
- 用户数据隔离、重复评分、重复钱包、微额精度。
- 支付不确定性与预算保留；交付失败后的免费重试。
- AWS Payments 请求参数对 boto3 service model 的校验。
- 复用已有 Stripe/Privy instrument，不创建钱包；校验付款 userId、connector 类型、ACTIVE 状态、账户权限及余额单位。
- Runtime `/ping`、`/invocations` 协议。
- 桌面完整购买流程、CSV 导出、设置、键盘关闭弹窗及手机布局。
- 桌面／手机独立登录页无注册入口、错误密码提示、已有账户邮箱验证和密码重置；浏览器测试模拟 Cognito 响应，不发送验证邮件。
- 本地 EVM 中的合约身份权限、任务完成权限、评分防重与历史失效。

CDK synth、容器运行、本地 EVM 和 SDK schema 校验均不替代 AWS 实际部署验证或 Base Sepolia 真实资金链路测试。

## AWS 登录与访问排查

- `/login` 由 CloudFront Function 路由到 S3 应用入口。前端默认走同域 `/api/*`，CloudFront 通过 VPC Origin 访问内部 ALB。
- VPC Origin 必须显式设置 `HTTP_ONLY` 与端口 `80`，与内部 ALB listener 一致。默认 `match-viewer` 会尝试访问未配置的 HTTPS/443。ALB 安全组使用 `com.amazonaws.global.cloudfront.origin-facing` 托管前缀列表。
- AWS 不允许原地修改已关联 distribution 的 VPC Origin。若修改 endpoint 配置，应使用新的 CDK construct ID 创建替代 origin，让 CloudFormation 切换 distribution 后清理旧资源；创建和删除可能各需要数分钟。
- `/api/health` 检查数据库连通性；`/api/me` 在无令牌时应返回 `401`。单独访问 S3 对象 URL 应返回 `403`。
- 新账户由管理员创建。已有未验证账户可继续验证邮箱，验证码过期可在确认页面重新发送；忘记密码使用登录页的 **Forgot password?**。
- 专用演示账户 `demo@agentmarketplace.example` 使用独立 Cognito subject，通过 `ShowcaseUserSub` 和明确的任务／Agent ID 列表读取现有测试数据。该演示邮箱使用保留的 `.example` 域，不接收邮件；需要变更密码时由管理员处理。不要把展示账户绑定到原付款钱包，也不要复制已结算支付来填充展示数据。
- Cognito 的 `AdminCreateUserConfig.AllowAdminCreateUserOnly` 必须为 `true`，CDK 中的 `selfSignUpEnabled` 必须为 `false`。`SignUp is not permitted for this user pool` 是预期的自助注册拒绝结果，不应再启用该功能。`scripts/verify_deployment.py` 会检查注册关闭，以及邮箱验证和密码登录配置。
- `PaymentOwnerSub` 与 Cognito `/api/me` 的 `id` 对应，原有 `PaymentUserId` 与 AgentCore 钱包对应，两者不能互换。
- `PaymentDelegateSub` 可为另一个明确的 Cognito 账户授予同一测试钱包的付款权限；`PaymentDelegateLimitMicros` 是管理员设置的累计付款加预留上限（默认 1 测试 USDC），账户自己的预算不能突破它。两个配置同时部署到 API 和编排 Runtime。清空 delegate 参数可撤销权限；仅设置只读 showcase 不会开放支付。账本按登录账户分别归属，钱包实际资金共用。
- 支付资源配置以 CloudFormation 参数为准，账户钱包映射保存在 RDS。参数部署完成后，可运行 `scripts/bind_aws_wallet.py --region us-east-1` 为指定且已登录过的账户绑定现有钱包；同一绑定可重复验证，不替换其他钱包，也不调用付款接口。当前绑定结果见 `artifacts/aws-wallet-binding.json`。
- AWS 通过 `scripts/seed_aws.py` 初始化 8 个共享演示 profile，新用户登录即可使用。演示记录使用 `demo-` ID 和独立系统 owner，收款字段为非钱包的内部标识，API 返回 `wallet: null`、`is_demo: true`、`bookable: true`。演示任务选标后进入 `demo_ready`，可直接调用交付接口；付款接口始终拒绝演示任务。演示身份由服务端数据判断，客户端不能为付费任务指定免费模式。交付和反馈保存在个人任务中，不改变消费额度、支付记录或公开信誉。脚本重复执行不会改写已有用户或交易。
- 上线验证产生的临时账户、任务与 profile 应在测试后清除，共享演示目录应保留。
