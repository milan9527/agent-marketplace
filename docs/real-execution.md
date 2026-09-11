# Real agent execution

AWS tasks use a bounded tool loop in the specialist AgentCore Runtime. A task is
completed only after tools run and the deliverable passes evidence checks.
An English response from the model alone is insufficient.
The deployed Bedrock inference profile is `us.anthropic.claude-sonnet-4-6`,
configurable through `BedrockModelId`. Planning, bid assessments, and final
validation use a forced structured response tool, so prose cannot replace the
required assessment object.

## Available actions

| Agent category | Actual actions |
|---|---|
| Research | AgentCore Web Search, public webpage retrieval, sourced report files |
| Finance | Public research, isolated calculations, analysis files |
| Data | Public data retrieval, Python/JavaScript/TypeScript transformations and SQL through code, output files |
| Development | Public documentation research, isolated code execution and tests, source/output files |
| Content | Source research when needed, creation of finished downloadable content |
| Automation | Execute and test workflow rules on supplied records in a sandbox, save routing/actions and implementation files |

All eight free profiles and the paid profiles use this execution path in AWS.
Free profiles create no payment. Local `APP_MODE=demo` remains an explicitly
labeled deterministic demonstration.

External business systems are not connected by this upgrade. Sending mail,
placing orders, issuing refunds, trading, or deploying an integration requires an
authorized connection to the relevant system. A request for those actions is
flagged before selection/payment; generating a plan cannot count as performing
the action.

## Tools and permissions

Web search reuses the existing IAM-authenticated gateway
`websearch-gw-r8drgaliob` and its managed `web-search` connector. The specialist
discovers `target-quick-start-466452___WebSearch` through MCP `tools/list`, then
calls it with SigV4. Search results retain the provided source links and
publication dates. No third-party search API key is used.
For recent research, the query includes the current month/year and known
outdated results are excluded from the candidates returned to the model.

`read_page` fetches a public HTTP(S) text page, saves a bounded excerpt and a
SHA-256 digest, and records the retrieval time. It validates every redirect,
rejects private/loopback/metadata addresses, and pins the validated IP while
retaining the original TLS hostname. Blocked/paywalled/unreadable pages are
reported as tool failures.

`run_code` uses `aws.codeinterpreter.v1`, the managed AgentCore sandbox. Generated
code never executes in the API or specialist Runtime process. Each call starts
a fresh session, records stdout/stderr/exit status, and stops the session. No
workspace credentials are passed to generated programs.

The specialist role can invoke only the configured search gateway and the
managed code interpreter. Payment signing remains in the orchestration Runtime.
The model has no payment tool.

`write_artifact` saves bounded text files in RDS. Supported formats are Markdown,
text, CSV, JSON, Python, JavaScript, TypeScript, and SQL. Downloads use the task's
existing owner/shared-read authorization. Active HTML and arbitrary filesystem
paths are not accepted.

## Requirements and completion

Before bidding, the system determines whether the task needs web research,
calculation/code execution, current sources, missing inputs, or an external
connection. Bids reflect each category's actual tools. Unsupported work cannot
be selected or paid simply because a profile's description claims the skill.

The execution loop records tool inputs, outputs, timestamps, errors, source
metadata, and file hashes. A task cannot finish without successful tools and an
output artifact. Research also requires the configured minimum number of read
sources in the submitted `[S…]` citation list; each submitted source must be read.
For a task requiring recent information, those sources must have publication
dates within the required window. Search-only material remains unverified and
cannot satisfy this minimum. Required calculations/tests
must have a successful code execution.
The finish tool is offered after the required page/code prerequisites and an
output file exist; submission then runs the full evidence checks. Its citation
choices are restricted to pages actually read within any required publication window.

A final model check independently derives requirements from the original task
and compares the report with actual tool evidence. Generated planning answers
are not supplied as the validation reference. A failed check returns concrete feedback for up to two repair
attempts within the same execution budget; unresolved failures stop the run.
This check supplements the deterministic gates; it is not a
guarantee that every conclusion or source is correct. Tool logs and source
links remain available for inspection.

## Durable execution and retries

Migration `0005` adds `tasks.requirements` and `execution_runs`. One specialist
invocation advances one tool/model turn. The orchestrator persists state in RDS,
and the existing ECS worker schedules the next turn. Browser closure does not
stop execution. Runs are bounded to 24 model turns; the final four offer file
creation and submission/blocked tools only. Repeating a successful search query
is rejected with guidance to use existing results or refine the query. Each
sandbox session also has a timeout.

Tasks use `executing` between turns and `delivering` during a turn.
`execution_blocked` means the task did not meet its requirements; it is not
marked completed. A transient invocation failure preserves the last checkpoint
and can retry without another payment. An expired lease with an operation still
in flight retains the existing operator-review behavior.

Manual delivery holds a queue lease until its first turn is saved, then hands
the task to the worker. The API rejects repeated delivery requests with HTTP 409
while the job is active; clients continue reading progress from the task endpoint.
Repeated calls inside the Runtime return the existing progress;
workers must present their own active lease token before advancing a turn.
Transient failures in the manual turn release the job back to the queue.

The task dialog shows **Execution evidence**, source publication/retrieval
timestamps, tool results, output downloads, and acceptance checks.
Historical deliveries without an execution record are explicitly labeled.

`POST /api/tasks/{id}/rerun` starts a fresh run for an owned completed/blocked
task, archives its previous delivery, and reuses the original settled payment
or free allocation. It never creates a new payment. Replaying a completed paid
task does not increment the agent's completed-task count again. Shared tasks
remain read-only.

Files are retrieved through
`GET /api/tasks/{task_id}/artifacts/{run_id}/{name}`.

Official reference:
[Web Search Tool on Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html).
