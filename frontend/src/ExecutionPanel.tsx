import {
  ArrowDownToLine,
  CheckCheck,
  Clock3,
  ExternalLink,
  Workflow,
} from "lucide-react";
import type { Execution } from "./types";

export const toolNames: Record<string, string> = {
  web_search: "AgentCore Web Search",
  read_page: "Read source page",
  run_code: "AgentCore Code Interpreter",
  write_artifact: "Create output file",
  finish: "Submit for validation",
  blocked: "Execution stopped",
};

export default function ExecutionPanel({
  execution,
  download,
}: {
  execution: Execution;
  download: (name: string) => void;
}) {
  return (
    <section className="execution-panel" aria-label="Execution evidence">
      <h3>
        <Workflow size={19} /> Execution evidence
      </h3>
      <p>
        {execution.status === "completed"
          ? "Tools ran and the result passed evidence checks."
          : execution.status === "validating"
            ? "Checking the result against the task and tool outputs."
            : execution.status === "blocked"
              ? "Execution stopped before the task requirements were met."
              : "The agent is using tools. Progress is saved after each step."}
      </p>
      <small>
        Started {new Date(execution.started_at).toLocaleString()} ·{" "}
        {execution.steps} steps
      </small>
      {execution.error && (
        <div className="form-note warning" role="status">
          {execution.error}
        </div>
      )}
      <ol className="execution-timeline">
        {execution.trace.map((step) => (
          <li key={step.id}>
            <details>
              <summary>
                {step.status === "succeeded" ? (
                  <CheckCheck size={15} />
                ) : (
                  <Clock3 size={15} />
                )}
                <strong>{toolNames[step.tool] || step.tool}</strong>
                <span>{step.status}</span>
                <small>
                  {Math.max(
                    0,
                    (Date.parse(step.finished_at) -
                      Date.parse(step.started_at)) /
                      1000,
                  ).toFixed(1)}
                  s
                </small>
              </summary>
              <pre>
                {JSON.stringify(
                  { input: step.input, output: step.output },
                  null,
                  2,
                )}
              </pre>
            </details>
          </li>
        ))}
      </ol>
      {execution.sources.length > 0 && (
        <div className="execution-sources">
          <h4>Sources</h4>
          {execution.sources.map((source) => (
            <div key={source.id}>
              <a href={source.url} target="_blank" rel="noopener noreferrer">
                [{source.id}] {source.title} <ExternalLink size={12} />
              </a>
              <small>
                {source.read ? "Page read" : "Search excerpt only"} · Published:{" "}
                {source.published_at || "Not provided"}
                {" · "}Retrieved:{" "}
                {new Date(source.retrieved_at).toLocaleString()}
              </small>
            </div>
          ))}
        </div>
      )}
      {execution.artifacts.length > 0 && (
        <div className="execution-artifacts">
          <h4>Output files</h4>
          {execution.artifacts.map((file) => (
            <button
              key={file.name}
              className="button secondary"
              onClick={() => download(file.name)}
            >
              <ArrowDownToLine size={15} /> {file.name}
              <small>{(file.bytes / 1024).toFixed(1)} KB</small>
            </button>
          ))}
        </div>
      )}
      {execution.validation && (
        <details className="execution-validation">
          <summary>
            Acceptance checks ·{" "}
            {execution.validation.passed ? "Passed" : "Needs attention"}
          </summary>
          <ul>
            {execution.validation.checks?.map((check, i) => (
              <li key={i}>
                <strong>
                  {check.passed ? "Pass" : "Fail"}: {check.requirement}
                </strong>
                <p>{check.evidence}</p>
              </li>
            ))}
          </ul>
          <p>{execution.validation.reason}</p>
        </details>
      )}
    </section>
  );
}
