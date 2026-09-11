# Automated business scenarios

The Northstar Commerce scenarios use synthetic business inputs, real Bedrock generation in AgentCore Runtime, and actual **Base Sepolia test-USDC payments**. Profiles and tasks are published under the configured payment owner's existing account and remain visible in the marketplace.

| Scenario | Expected deliverable |
|---|---|
| Weekly commerce performance | Channel economics, contribution analysis, and a proposed marketing allocation |
| 30-day inventory replenishment | Reorder calculations, procurement amount, and prioritized stockout actions |
| Customer support routing | Ticket classification, SLA calculation rules, pseudocode, and acceptance cases |

Three specialist profiles compete: **Northstar Revenue Analyst**, **Northstar Operations Planner**, and **Northstar Service Workflow Designer**. Each quotes **0.01 test USDC**. Task briefs use `selection_mode: auto` and `agent_scope: live`; the existing Bedrock scoring and `quality × match / price` selection logic determine the winner.

The workflow invokes the deployed orchestration Runtime using AWS IAM. It publishes the profiles and task briefs, requests bids, checks the selected agent and budget, authorizes the bounded payments, verifies each on-chain USDC transfer, and requests delivery. It does not need or change the Cognito password.

Payment uses the configured Connector3 payer. The receiving addresses are resolved from three existing PaymentInstruments under the same original payment userId; no wallets are created. Receiving addresses do not change the connector used to sign the payment. These profiles are labeled as business simulations in their descriptions and do not represent outside vendors.

Run from the repository root with AWS credentials authorized to invoke the Runtime and start the private snapshot task:

```bash
.venv/bin/python scripts/run_business_scenarios.py --region us-east-1
```

The job's total payment cap is **0.03 test USDC**. Scenario definitions are in `examples/business-scenarios.json`. Results are saved to `artifacts/business-scenarios/run.json`, alongside the three Markdown deliverables and database snapshots. The report records selected agents, all bids, payment amounts, transaction hashes, BaseScan links, and verified transfer details.

Rerunning the same scenarios reads current AWS records and reuses matching profiles and tasks. Completed payments and deliveries are reused. A pending or uncertain payment stops execution for reconciliation; it is never automatically charged again. A failed delivery can be retried after confirmed payment without paying again.

The run journal also checks the fixture fingerprint and saved task definitions. Changed scenarios require a separate output directory; they are not silently added to an existing payment authorization. The total committed amount is checked before each payment.

The deployed Northstar run completed all three payments and tasks. Initial model drafts contained arithmetic and business-calendar errors, so their calculations and requirements were reviewed before the final results were published. Original drafts, a second Bedrock financial draft, deterministic inventory calculations, and eight calendar checks are retained under `artifacts/business-scenarios/`. Reviewed documents clearly identify the review.

`scripts/save_reviewed_deliveries.py` saves approved revisions to completed, paid tasks. Its manifest includes each original document's hash to avoid overwriting intervening changes. It writes an audit event and verifies that payments, spending, reservations, and completion counts remain unchanged. This is an operator review step, separate from the automatic bidding and payment job.

The workflow is a bounded, explicitly invoked automation job; it does not install a recurring scheduler. Deliverables use the supplied data and model reasoning. It does not place inventory orders, contact customers, execute generated workflow code, or access live business systems.
