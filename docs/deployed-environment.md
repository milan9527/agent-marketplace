# Deployed environment

AWS account `632930644527`, region `us-east-1`, stack `AgentMarketplace`.

- **Login:** https://dp7428wrh61ns.cloudfront.net/login
- **Marketplace:** https://dp7428wrh61ns.cloudfront.net
- **API health:** https://dp7428wrh61ns.cloudfront.net/api/health

Sign in with an account provided by your workspace administrator. Cognito self-registration is disabled, and the login page has no account-creation entry point. Existing accounts retain password login, recovery, and email verification. The entire interface is in English. All users can use eight shared demo agents from the local catalog, including Atlas Research, Finley Finance, and CodeCraft. Cards are labeled **Demo**, support search and category filters, and offer **Try agent**.

To try the full workflow, choose **Post a task → Post task & get bids → Choose demo agent → Run demo**. AgentCore Runtime calls Bedrock and actual tools to perform the task, saves execution evidence in RDS, and validates the deliverable before completion. Demo runs require no wallet, create no payment, and do not affect public paid-task reputation. Example quotes help demonstrate bid comparison. Each user's tasks, payments, and published agents remain separate. Live agents still require confirmed payment before delivery.

The catalog is stored in RDS. Initialize or safely rerun it with `.venv/bin/python scripts/seed_aws.py --region us-east-1`; this preserves existing profiles and user records.

The task form supports **I'll choose an agent** and **Automatic: bid, pay & run**, with separate demo and paid agent pools. Automatic mode authorizes payment within the task budget and account allowance, then runs bidding, selection, AgentCore Payments settlement, and delivery in the background. Selection requires at least 70% match and a quote within budget, then maximizes `quality × match / price`. Existing tasks can opt in with **Run automatically**. **Choose best agent** alone retains selection-only behavior. See [bidding and selection](bidding-and-selection.md).

## Dedicated demo account

The separate Cognito account is **`demo@agentmarketplace.example`**, with subject `b43834c8-6051-7049-8bbb-f8450019dea5`. It was created by an administrator with a permanent password, without sending an invitation. Its password is supplied separately and is not stored in the repository. Cognito self-registration remains disabled.

This account can browse all **11 agents**: the eight free demo profiles and three Northstar business specialists. **My agents** also shows the three business profiles with a **Shared** label.

Discover and My agents keep separate search, category, and Featured filters. Filtering the public catalog no longer hides the account's three shared profiles when switching pages. An account with no published or shared profiles sees **No agents published yet**, distinct from a filtered search with no matches.

**My tasks** includes all five existing test tasks: the three Northstar business scenarios and two completed crypto research tasks. The account can inspect the original bids, read and download the final deliverables, and view the three original testnet payment receipts. Shared tasks display **Shared · Read only** and cannot be quoted again, selected, paid, delivered again, or rated by this account.

Sharing uses explicit task/agent IDs and the configured demo account's Cognito subject. Original ownership and payment records remain unchanged; no copies of settled payments are created. The demo account can post its own tasks and use free demo agents.

The demo account is also explicitly authorized by `PaymentDelegateSub` to use the existing Connector3 Stripe/Privy test wallet for its own paid tasks. Its total allowance is **1 test USDC**, including settled payments and reservations, enforced in both the API configuration and the payment Runtime. Wallet funds are shared with the original account, while task ownership and spending records remain separate. The Payments wallet dialog displays this shared-wallet arrangement and the remaining personal allowance. Shared historical tasks remain read-only.

The sharing configuration is managed by the stack parameters `ShowcaseUserSub`, `ShowcaseTaskIds`, and `ShowcaseAgentIds`. New private tasks are not automatically shared. API and browser verification reports are `artifacts/aws-demo-verification.json` and `artifacts/aws-demo-browser-verification.json`.

## Resources

| Component | Deployment |
|---|---|
| Frontend | React static assets in private S3 bucket `agentmarketplace-webassets27872646-29cfpebtbqws` |
| HTTPS delivery | CloudFront distribution `E19OV7EU5URB6W`, with S3 Origin Access Control and SigV4 |
| API | ECS Fargate service `AgentMarketplace-ApiServiceC9037CF0-GA9GFHKzNodU`, ARM64, private subnets |
| Automatic tasks | Private ECS worker, RDS queue with leases, and AgentCore execution; service name in `WorkflowWorkerServiceName` |
| API connection | CloudFront VPC Origin → internal ALB on HTTP/80 → FastAPI on port 8000 |
| Database | Encrypted, private RDS PostgreSQL 16.15; Alembic migrations applied |
| Authentication | Cognito user pool `us-east-1_8eNWPxRFK` |
| Orchestration | AgentCore Runtime `marketplace_orchestrator-GJgJvhDDCB` |
| Bidding and tool execution | AgentCore Runtime `marketplace_bidders-U2mRv6Ewxn`, Claude Sonnet 4.6 through Amazon Bedrock |
| Web research | Existing AgentCore Gateway `websearch-gw-r8drgaliob`, managed Web Search connector, IAM authentication |
| Calculations and tests | AgentCore Code Interpreter `aws.codeinterpreter.v1`, isolated sessions |

## Validation

Validated on September 11, 2026:

- The demo account connected Connector3 through the public browser UI and paid its own crypto research task for **0.01 test USDC**. The Base Sepolia receipt's USDC sender, recipient, and amount were verified independently; the task subsequently completed. The local report for that payment is `artifacts/demo-payment-browser.json`.
- The dedicated demo account passed real password sign-in on desktop and mobile, displayed all five shared test tasks and eleven agents, and downloaded a report matching the database content hash. Shared payment/delivery actions returned `403`. Wallet access was initially disabled and is now granted separately through the explicit payment delegate configuration.
- All **78 backend tests** pass against SQLite and PostgreSQL, covering automatic workflows, concurrent workers, manual-delivery leases, payment delegation, spending caps, uncertain-payment reservations, delivery retries, account isolation, and real-execution evidence gates. **14 desktop/mobile browser cases** cover automatic and manual tasks, the free demo workflow, shared-account access, independent catalog filters, and execution evidence/downloads. Automatic tests assert that the browser does not send payment requests.
- Real Cognito password sign-in, authenticated API identity, session reload, and anonymous API rejection passed through the public CloudFront URL.
- Self-registration is disabled in Cognito (`AllowAdminCreateUserOnly: true`), and a direct `SignUp` request is rejected. The existing account, password policy, and email verification settings were preserved.
- Both the public desktop/mobile login page and Cognito hosted sign-in omit account creation. Six login browser tests cover sign-in, password recovery, and verification of existing accounts.
- A temporary agent and task exercised CloudFront → ECS → orchestration Runtime → bidder Runtime → Bedrock. The resulting task and bid were persisted in RDS.
- Public desktop and mobile login pages were checked in Chromium.
- A newly created Cognito account saw all eight shared demo profiles through the public site, could search and preview them on desktop and mobile, and had empty personal tasks, payments, and published-agent lists.
- Through the public website, a new account posted a task, received eight demo bids, selected an agent, ran a real Bedrock delivery, downloaded the result, and submitted private feedback. Reloading and opening the same task on mobile preserved the result.
- Demo delivery created no payment and left spending, reserved funds, and public agent reputation unchanged. Direct payment attempts were rejected; repeated delivery returned the saved result.
- Real Bedrock bidding automatically selected the highest qualifying value within the selected pool, persisted its reason, and generated a demo deliverable. Manual selection also passed through the public UI.
- A temporary paid profile was selected automatically and remained `awaiting_payment`. Unpaid delivery was rejected, no payment was created, and a different account could not bind the configured owner's wallet.
- The temporary Cognito account and its database records were removed after verification.
- The existing Connector3 Stripe/Privy wallet was bound to `milan9527@hotmail.com` in RDS. A separate database session verified the saved mapping and the account/wallet API handlers under the deployed ECS role; budget, spending, reservations, and payment records were unchanged.
- No payment was initiated during the preceding infrastructure and free-demo checks. The paid business scenarios below were subsequently run with explicitly authorized test-USDC payments.

Run the read-only infrastructure checks again with:

```bash
.venv/bin/python scripts/verify_deployment.py --region us-east-1
```

Deployment outputs and verification results are saved under `artifacts/`. Login screenshots are `artifacts/aws-login-desktop.png` and `artifacts/aws-login-mobile.png`; catalog screenshots are `artifacts/aws-demo-catalog-desktop.png` and `artifacts/aws-demo-catalog-mobile.png`. The full demo run is recorded in `artifacts/aws-demo-run-verification.json`, with desktop/mobile screenshots in `artifacts/aws-demo-run-desktop.png` and `artifacts/aws-demo-run-mobile.png`, and the generated output in `artifacts/aws-demo-delivery.md`.

Manual and automatic selection checks are recorded in `artifacts/aws-selection-verification.json`; screenshots are `artifacts/aws-auto-selection-desktop.png` and `artifacts/aws-auto-selection-mobile.png`.

The registration policy and live login checks are recorded in `artifacts/aws-registration-verification.json`. The check created no accounts and sent no emails.

## Real tool execution verification

Six owned tasks were completed with actual tool evidence on September 11, 2026.
The original **collect popular smart device market** task was rerun using
AgentCore Web Search and public webpage retrieval. It read four current sources
covering smart homes, smartwatches, smartphones, and smart speakers. A separate
IoT source could not be read; the report explicitly labels that section as
search-snippet information. It does not count toward the four read sources.

| Work | Actual result |
|---|---|
| Smart device research | Four source pages read, publication/retrieval dates retained, Markdown report saved |
| BrightCart contribution analysis | Code calculated USD 3,100 contribution, 38.75% margin, and 6.67 combined ROAS |
| BrightCart inventory planning | Code calculated 168 mugs and 50 lamps to replenish, total cost USD 2,276 |
| BrightCart support workflow | Code executed routing and calendar rules; P1 deadlines Monday 10:30, P2 Monday 16:30, P3 Tuesday 16:30, P0 Friday 16:45 UTC; mixed intents require human review |
| Order aggregation development | Downloadable implementation and tests; 21 published tests and 10 independent checks passed in AgentCore Code Interpreter |
| LumaDesk content | Finished English product-page Markdown created from the supplied fictional facts |

The development case was explicitly clarified after an independent check found
that a non-dictionary row raised `TypeError`. The agent reran the task, generated
corrected code, and executed its tests. The published files were downloaded,
checked against their saved SHA-256 hashes, and executed again in a separate
AgentCore sandbox. Their previous execution record is retained.

An additional free Content task verified manual delivery: the initial API call
handed execution to the background worker, which completed `order_status.md`.
Duplicate delivery requests did not create another run. The API rejects requests
while the job is active with HTTP 409 and returns the saved result after completion.
The downloaded file matched its stored SHA-256 hash, and no payment was created.

The three paid tasks reused their original settled orders for every rerun. Verification created
**no new wallet payment**, and the demo account's spending remained **0.05 test
USDC**, with zero reserved. The two newly created verification tasks used free
demo agents. Synthetic commerce/support inputs remain simulations; no orders,
refunds, campaign changes, or customer messages were sent.

Real desktop/mobile password login verified the execution timeline, source links,
acceptance checks, and authenticated file downloads. Download hashes matched the
stored artifacts, and the browser made no marketplace write requests. The demo
account can still see all 11 agents, its 16 visible tasks, and the existing wallet.
Cognito self-registration remains disabled.

Reports, source files, and screenshots are under `artifacts/real-agent-tools/`.
The task verification script reruns its four existing owned tasks and creates
two free tasks if absent; its journal prevents blind duplicate requests.

```bash
.venv/bin/python scripts/verify_real_execution.py --credentials-file /secure/demo-credentials.json
.venv/bin/python scripts/verify_published_code.py
.venv/bin/python scripts/verify_manual_execution.py --credentials-file /secure/demo-credentials.json
node scripts/verify_real_execution_browser.mjs /secure/demo-credentials.json
```

The earlier business reports below describe historical text generation and
operator review. Historical deliveries without tool records are labeled in the
interface and are not evidence of live web or code execution.

## Automatic paid workflows

The dedicated demo account ran three BrightCart tasks for **0.01 test USDC each**. A new daily contribution report was posted through the public UI in **Automatic: bid, pay & run** mode. The browser closed immediately after the task was created; its only marketplace write was `POST /api/tasks`. The ECS worker then completed bidding, payment through Connector3, and AgentCore delivery. Two previously pending tasks explicitly opted into the same workflow.

| Task | Selected agent | Base Sepolia transaction |
|---|---|---|
| Automatic daily contribution report | Northstar Revenue Analyst | [0x6af030…18fa](https://sepolia.basescan.org/tx/0x6af030b8e429dcb30127c0923c05697ca1df8f12b9627d3d8f471b74c06918fa) |
| Stockout prevention and replenishment plan | Northstar Operations Planner | [0x43eb9d…d069](https://sepolia.basescan.org/tx/0x43eb9d7d1f44e5b2b011ba36de02f1149e9e49914f71e0799f5e0b5876e5d069) |
| Support ticket routing and SLA workflow | Northstar Service Workflow Designer | [0x39e9fa…5355](https://sepolia.basescan.org/tx/0x39e9facbcef18eede9cf982d4243336925657eb0f287b85177486371558a5355) |

The daily report and support workflow completed without operator intervention. Inventory payment paused when the facilitator returned no valid settlement receipt. Recovery reused the original payment session, idempotency tokens, and signed authorization; a verified transfer was reconciled into the original payment record before resuming delivery. No replacement payment was created. After this run, the demo ledger recorded **0.05 test USDC spent**, **zero reserved**, and **0.95 USDC remaining**, including its two earlier payments.

Delivery review separately corrected inventory arithmetic and support SLA deadlines. The reviewed documents identify those corrections; the automatically generated originals remain in the local artifacts. The daily report correctly calculated USD 3,100 contribution from the supplied figures. Successful workflow completion does not constitute automatic business-content validation.

Evidence is in `artifacts/automatic-workflow/`: browser creation and closure, task states, chain receipts, original and reviewed documents, reconciliation, and desktop/mobile download checks. The live verification scripts are `scripts/verify_automatic_browser.mjs`, `scripts/verify_automatic_workflow.py`, and `scripts/verify_automatic_results.mjs`. The first creates a paid test task and refuses to run over an existing report; inspect prior results before any new paid run.

## Existing Stripe/Privy wallet

The stack references the existing PaymentManager:

```text
arn:aws:bedrock-agentcore:us-east-1:632930644527:payment-manager/demopaymentmanager-zy4lsroxj3
```

The existing wallet is configured in the ECS API and orchestration Runtime and bound to the site's existing account in RDS:

| Field | Value |
|---|---|
| Login account | `milan9527@hotmail.com` |
| Cognito owner sub | `c4f85478-20e1-7091-fdfc-ceadde2f8cca` |
| Original AgentCore payment userId | `demo-user` |
| Connector | `mystripeprivyconnector3-wbtiy89xwz` (Connector3, StripePrivy, READY) |
| PaymentInstrument | `payment-instrument-a7YCWrAefB6h15Z` |
| Wallet address | `0xac80AcB75B732f4E2141A0B0785BfD79F745F045` |
| Network | **Base Sepolia testnet** |
| Instrument status | `ACTIVE` |
| Balance at verification | **19.868000 test USDC**, September 11, 2026, 04:41 UTC |

Sign in as the configured owner or explicit payment delegate and open **Payments → Stripe / Privy wallet** to view the current address, status, and balance. Other accounts do not inherit access. The AgentCore payment userId is independent of the Cognito account; it was recovered from an existing payment integration's configuration.

Connector3 uses credential provider `DemoPaymentManager-MyStripePrivyConnector3-stripe-privy`. The wallet address matches the configured Privy authorization ID's owner/additional-signer metadata. The other connector also named Connector3 (`mystripeprivyconnector3-y5qlv7opbw`) references Connector2's credential provider and is not selected.

The authoritative binding report is `artifacts/aws-wallet-binding.json`. It confirms the persisted user/instrument mapping, `wallet_connected: true`, ACTIVE status, and balance using the application's account and wallet API handler functions in a private ECS task. This check did not use a browser login or exercise payment settlement. It created no wallet or payment and left spending limits, spent funds, and reservations unchanged. The earlier `artifacts/aws-connector3-verification.json` records discovery before this binding.

A read-only check of `https://x402.org/facilitator/supported` confirmed x402 v2, `eip155:84532`, and the `exact` scheme; see `artifacts/aws-payment-facilitator-check.json`. Signing and settlement still require an explicitly authorized payment and were not tested during binding.

To repeat the administrative binding verification, run `.venv/bin/python scripts/bind_aws_wallet.py --region us-east-1`. The same binding is safe to rerun; the script refuses to replace a different wallet. See [AWS deployment](aws-deployment.md) for the setup and payment workflow.

## Paid business scenarios

On September 11, 2026, three Northstar specialist profiles and three tasks were published under `milan9527@hotmail.com`. Each task received three bids and automatically selected its specialist at 95% match for 0.01 test USDC. All three tasks reached `completed`, and all three payments reached `settled`.

| Task | Selected agent | Confirmed Base Sepolia transaction |
|---|---|---|
| Weekly commerce performance review | Northstar Revenue Analyst | [0x276332…05d36](https://sepolia.basescan.org/tx/0x2763323d785176230c4d00ef0e9f3d1c417cb491c155d1fc57e8affdc4f05d36) |
| 30-day inventory replenishment plan | Northstar Operations Planner | [0x432a12…2194a](https://sepolia.basescan.org/tx/0x432a12f6f25e03d721ad1965303eee287a69a86641711fa455c3c881df62194a) |
| Customer support routing and SLA design | Northstar Service Workflow Designer | [0xd3d09e…3386](https://sepolia.basescan.org/tx/0xd3d09ea808ba63ec130aa7ab7927120f0b220e1e289570e052fc63f186ba3386) |

Each transaction's successful receipt and USDC transfer log were checked against the expected payer, recipient, token contract, and 10,000-unit amount. Total paid was **0.030000 test USDC**. The payer's balance was **19.838000 test USDC** after execution; the application recorded 0.030000 spent and zero reserved. The original two user tasks and shared demo catalog were preserved.

The run corrected two payment integration issues: reading the nested AWS `paymentSession` response, and wrapping AgentCore's raw signature/authorization inside the x402 v2 `paymentPayload` envelope. One later settlement did not return a receipt the application could confirm. The first two payments were reconciled by reusing their original idempotent process results and signed authorizations, verifying the resulting on-chain transfers, and updating the original payment records. No second payment record or duplicate transfer was created. The third payment settled through the updated orchestration Runtime.

Bedrock generated all three initial deliverables. Marketplace review corrected arithmetic and SLA errors and completed missing requirements; original drafts and review records are retained. These results use synthetic business inputs and do not represent live commerce data, placed purchase orders, or deployed support integrations.

See [the business scenario workflow](business-scenarios.md) and `artifacts/business-scenarios/` for the run journal, original and reviewed deliverables, transaction receipts, calculation checks, and reconciliation records.
