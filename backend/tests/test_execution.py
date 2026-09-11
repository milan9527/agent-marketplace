from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app import tools
from app.agents import converse_structured
from app.execution import (
    Requirements,
    capability_error,
    citable_sources,
    completion_error,
    execute_step,
    execute_tool,
    plan_task,
    validate_result,
)
from app.execution_service import advance_execution, rerun_execution
from app.db import session_factory
from app.models import Agent, AutomationJob, ExecutionRun, Payment, Task


def requirements(**changes):
    return {
        "summary": "Research current devices",
        "web": True,
        "code": False,
        "artifact": True,
        "minimum_sources": 2,
        "freshness_days": 30,
        "external_actions": [],
        "missing_inputs": [],
        "acceptance_criteria": ["Read and cite current sources"],
        **changes,
    }


def state(**changes):
    return {
        "requirements": requirements(),
        "trace": [],
        "sources": [],
        "artifacts": [],
        "steps": 0,
        "messages": [],
        "status": "running",
        **changes,
    }


def test_capabilities_reject_external_writes_missing_inputs_and_missing_tools():
    assert "connection" in capability_error(
        requirements(external_actions=["Refund order"]), "Automation"
    )
    assert "missing" in capability_error(
        requirements(missing_inputs=["sales.csv"]), "Data"
    )
    assert "execute" in capability_error(requirements(code=True), "Research")
    assert capability_error(requirements(code=True), "Finance") is None


def test_non_web_plans_accept_zero_sources_without_weakening_research(monkeypatch):
    plan = requirements(web=False, code=True, minimum_sources=0, freshness_days=None)
    monkeypatch.setattr("app.agents.converse_structured", lambda *a: plan)
    assert plan_task({"title": "Calculate supplied numbers"})["minimum_sources"] == 0
    with pytest.raises(ValidationError, match="at least one source"):
        Requirements.model_validate({**plan, "web": True})


def test_repeated_successful_search_requires_a_new_query(monkeypatch):
    search = MagicMock()
    monkeypatch.setattr(tools, "web_search", search)
    s = state(
        trace=[
            {
                "tool": "web_search",
                "status": "succeeded",
                "input": {"query": "Device Market September 2026"},
            }
        ]
    )
    with pytest.raises(ValueError, match="Do not repeat"):
        execute_tool("web_search", {"query": " device  market September 2026 "}, s, {})
    search.assert_not_called()
    s["trace"][0]["status"] = "failed"
    search.return_value = {"sources": []}
    execute_tool("web_search", {"query": "Device Market September 2026"}, s, {})
    search.assert_called_once()


def test_search_filters_old_results_and_only_read_current_sources_are_citable(
    monkeypatch,
):
    recent = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        tools,
        "web_search",
        lambda query: {
            "query": query,
            "sources": [
                {
                    "url": "https://old.example",
                    "published_at": "2020-01-01",
                    "read": False,
                },
                {
                    "url": "https://current.example",
                    "published_at": recent,
                    "read": False,
                },
            ],
        },
    )
    s = state()
    result = execute_tool("web_search", {"query": "smart devices"}, s, {})
    assert result["excluded_outdated_sources"] == 1
    assert [v["url"] for v in result["sources"]] == ["https://current.example"]
    assert citable_sources(s) == []
    for source in s["sources"]:
        source["read"] = True
    assert citable_sources(s) == ["S2"]


@pytest.mark.parametrize(
    "stop,content",
    [
        (
            "end_turn",
            [{"text": "Here is the completed report instead of an assessment."}],
        ),
        (
            "max_tokens",
            [{"toolUse": {"name": "submit_result", "input": {"passed": True}}}],
        ),
    ],
)
def test_assessments_reject_free_text_and_truncated_tool_outputs(
    monkeypatch, stop, content
):
    client = MagicMock()
    client.converse.return_value = {
        "stopReason": stop,
        "output": {"message": {"role": "assistant", "content": content}},
    }
    monkeypatch.setattr("app.agents.boto3.client", lambda *a, **k: client)
    with pytest.raises(ValueError, match="complete structured"):
        converse_structured(
            "Assess only", {"task": "Build a report"}, {"type": "object"}
        )


def test_failed_validation_returns_actionable_feedback_then_stops(monkeypatch):
    result = {
        "passed": False,
        "checks": [
            {
                "requirement": "Correct business-hour deadline",
                "passed": False,
                "evidence": "The report disagrees with the executed calendar calculation.",
            }
        ],
        "reason": "Correct the SLA deadline.",
    }
    monkeypatch.setattr("app.agents.converse_structured", lambda *a: result)
    s = state(status="validating", steps=4, draft="Incorrect report", cited_ids=[])
    for _ in range(2):
        s = validate_result(s, {"title": "SLA calculation"})
        assert s["status"] == "running" and "report" not in s
        assert "Correct the SLA deadline" in s["messages"][-1]["content"][0]["text"]
    s = validate_result(s, {"title": "SLA calculation"})
    assert s["status"] == "blocked" and "Evidence validation failed" in s["error"]


def test_completion_requires_real_read_sources_freshness_and_matching_citations():
    report = (
        "An evidence-backed market analysis with explicit uncertainty. " * 3
        + "[S1] [S2]"
    )
    s = state()
    assert "No successful" in completion_error(s, report, ["S1", "S2"])
    s["trace"] = [{"status": "succeeded", "tool": "web_search"}]
    s["artifacts"] = [{"name": "analysis.md"}]
    assert "not retrieved" in completion_error(s, report, ["S1", "S2"])
    s["sources"] = [
        {
            "id": "S1",
            "read": False,
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
        {"id": "S2", "read": False, "published_at": None},
    ]
    assert "must be read" in completion_error(s, report, ["S1", "S2"])
    for source in s["sources"]:
        source["read"] = True
        source["published_at"] = "2020-01-01"
    assert "time window" in completion_error(s, report, ["S1", "S2"])
    for source in s["sources"]:
        source["published_at"] = datetime.now(timezone.utc).isoformat()
    assert completion_error(s, report, ["S1", "S2"]) is None
    assert "match" in completion_error(s, report + " [S3]", ["S1", "S2"])
    s["requirements"]["code"] = True
    assert "not executed" in completion_error(s, report, ["S1", "S2"])


def test_model_text_alone_never_completes_a_task(monkeypatch):
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "I searched and finished everything."}],
            }
        }
    }
    monkeypatch.setattr("app.execution.boto3.client", lambda *a, **k: client)
    payload = {
        "agent": {"category": "Research"},
        "task": {"title": "News", "spec": "Latest news"},
        "requirements": requirements(),
    }
    result = execute_step(payload)["execution_state"]
    assert result["status"] == "running" and not result["trace"]
    assert "report" not in result


def test_first_run_checkpoints_planning_before_another_model_call(monkeypatch):
    monkeypatch.setattr("app.execution.plan_task", lambda _: requirements())
    client = MagicMock()
    monkeypatch.setattr("app.execution.boto3.client", client)
    result = execute_step(
        {
            "agent": {"category": "Research"},
            "task": {"title": "Current research", "spec": "Find current sources"},
        }
    )["execution_state"]
    assert result["status"] == "running" and result["steps"] == 0
    assert result["requirements"] == requirements() and not result["trace"]
    client.assert_not_called()


@pytest.mark.parametrize(
    "stop,args,reason",
    [
        ("max_tokens", {"name": "output.md", "content": "incomplete"}, "truncated"),
        ("tool_use", {"name": "output.md"}, "missing required fields: content"),
    ],
)
def test_incomplete_file_calls_cannot_create_deliverables(
    monkeypatch, stop, args, reason
):
    client = MagicMock()
    client.converse.return_value = {
        "stopReason": stop,
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "incomplete",
                            "name": "write_artifact",
                            "input": args,
                        }
                    }
                ],
            }
        },
    }
    monkeypatch.setattr("app.execution.boto3.client", lambda *a, **k: client)
    save = MagicMock()
    monkeypatch.setattr(tools, "artifact", save)
    result = execute_step(
        {
            "agent": {"category": "Content"},
            "task": {"title": "Write a page", "spec": "Create content"},
            "requirements": requirements(web=False, minimum_sources=0),
        }
    )["execution_state"]
    assert result["status"] == "running" and not result["artifacts"]
    assert reason in result["trace"][0]["output"]["error"]
    save.assert_not_called()


@pytest.mark.parametrize("category,steps", [("Research", 0), ("Finance", 20)])
def test_unavailable_tool_cannot_run_even_if_model_requests_it(
    monkeypatch, category, steps
):
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "bad",
                            "name": "run_code",
                            "input": {"code": "print(1)"},
                        }
                    }
                ],
            }
        }
    }
    monkeypatch.setattr("app.execution.boto3.client", lambda *a, **k: client)
    run = MagicMock(side_effect=AssertionError("Unavailable tool must not execute"))
    monkeypatch.setattr(tools, "run_code", run)
    result = execute_step(
        {
            "agent": {"category": category},
            "task": {"spec": "Research", "title": "Research"},
            "requirements": requirements(),
            "execution_state": state(steps=steps) if steps else None,
        }
    )["execution_state"]
    assert result["trace"][0]["status"] == "failed"
    run.assert_not_called()
    if steps:
        offered = client.converse.call_args.kwargs["toolConfig"]["tools"]
        assert {s["toolSpec"]["name"] for s in offered} == {
            "write_artifact",
            "blocked",
        }


def test_search_discovers_managed_tool_and_retains_source_provenance(monkeypatch):
    gateway = MagicMock(
        side_effect=[
            {"tools": [{"name": "existing___WebSearch"}]},
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "results": [
                                    {
                                        "title": "Device release",
                                        "url": "https://publisher.example/release",
                                        "text": "An actual retrieved excerpt.",
                                        "publishedDate": "2026-09-09",
                                    }
                                ]
                            }
                        ),
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(tools, "gateway_call", gateway)
    result = tools.web_search("smart device launches")
    assert result["provider"] == "AgentCore Web Search"
    assert result["sources"][0]["read"] is False
    assert result["sources"][0]["published_at"] == "2026-09-09"
    assert gateway.call_args_list[1].args[1]["name"] == "existing___WebSearch"


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "fd00::1"]
)
def test_web_reader_rejects_private_and_metadata_destinations(monkeypatch, address):
    monkeypatch.setattr(
        tools.socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, (address, 443))],
    )
    with pytest.raises(ValueError, match="Private"):
        tools.public_address("https://example.com/news")


def test_reader_pins_dns_and_revalidates_redirects(monkeypatch):
    urls = []

    def resolve(url):
        if "169.254" in url:
            raise ValueError("Private destination")
        return urlsplit(url), "93.184.216.34"

    def respond(request):
        urls.append(
            (
                str(request.url),
                request.headers["host"],
                request.extensions["sni_hostname"],
            )
        )
        return httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )

    monkeypatch.setattr(tools, "public_address", resolve)
    original = httpx.Client
    monkeypatch.setattr(
        tools.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    with pytest.raises(ValueError, match="Private"):
        tools.read_page("https://example.com/news")
    assert urls == [("https://93.184.216.34/news", "example.com", "example.com")]


def test_code_uses_managed_sandbox_and_stops_session_on_error(monkeypatch):
    client = MagicMock()
    client.start_code_interpreter_session.return_value = {"sessionId": "isolated"}
    client.invoke_code_interpreter.return_value = {
        "stream": iter(
            [
                {
                    "result": {
                        "isError": True,
                        "structuredContent": {
                            "stdout": "",
                            "stderr": "AssertionError",
                            "exitCode": 1,
                        },
                    }
                }
            ]
        )
    }
    monkeypatch.setattr(tools.boto3, "client", lambda *a, **k: client)
    result = tools.run_code("assert 2 + 2 == 5")
    assert result["is_error"] and result["exit_code"] == 1
    client.stop_code_interpreter_session.assert_called_once()
    args = client.invoke_code_interpreter.call_args.kwargs
    assert (
        args["name"] == "executeCode"
        and args["arguments"]["code"] == "assert 2 + 2 == 5"
    )


def test_artifacts_cannot_escape_paths_or_render_active_html():
    for name in ["../output.txt", "a/b.txt", "x.html", "x.svg"]:
        with pytest.raises(ValueError):
            tools.artifact(name, "content")
    saved = tools.artifact("computed.csv", "product,total\nmug,12")
    assert saved["bytes"] and len(saved["sha256"]) == 64


def paid_task(client):
    response = client.post(
        "/api/tasks",
        json={
            "title": "Compute unit economics",
            "spec": "Revenue 5000, cost 2500. Compute margin.",
            "category": "Finance",
            "budget": "0.05",
            "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "preferred_agent_id": "finley",
        },
    )
    task = response.json()
    bid = client.post(f"/api/tasks/{task['id']}/quote").json()["bids"][0]
    client.post(f"/api/tasks/{task['id']}/select", json={"bid_id": bid["id"]})
    assert client.post(f"/api/tasks/{task['id']}/pay").status_code == 200
    return task


def claim_delivery(db, task_id):
    job = db.get(AutomationJob, task_id)
    job.status, job.lease_token = "running", "test-worker"
    job.lease_until = int(time.time()) + 600
    db.commit()
    return advance_execution(db, "demo-user", task_id, job_lease_token="test-worker")


@pytest.mark.parametrize("fails", [False, True])
def test_manual_delivery_holds_a_lease_then_hands_work_to_the_queue(
    client, monkeypatch, fails
):
    from app.automation import advance_automation

    task = paid_task(client)

    def invoke(_):
        with session_factory()() as observer:
            job = observer.get(AutomationJob, task["id"])
            assert job.status == "running" and job.lease_until > time.time()
            assert advance_automation(observer) == {"processed": False}
            assert (
                advance_execution(observer, "demo-user", task["id"])["status"]
                == "delivering"
            )
        if fails:
            raise RuntimeError("Transient runtime failure")
        return {"execution_state": state(requirements=requirements(web=False), steps=1)}

    call = MagicMock(side_effect=invoke)
    monkeypatch.setattr("app.agents.call_bidders", call)
    with session_factory()() as db:
        if fails:
            with pytest.raises(HTTPException) as exc:
                advance_execution(db, "demo-user", task["id"])
            assert exc.value.status_code == 502
        else:
            assert (
                advance_execution(db, "demo-user", task["id"])["status"] == "executing"
            )
    with session_factory()() as db:
        job = db.get(AutomationJob, task["id"])
        assert (
            job.status == "queued" and job.lease_token is None and job.lease_until == 0
        )
        assert db.get(Task, task["id"]).status == "executing"
        # A repeated API call observes the queued execution instead of racing the worker.
        assert advance_execution(db, "demo-user", task["id"])["status"] == "executing"
        with pytest.raises(HTTPException) as exc:
            advance_execution(
                db, "demo-user", task["id"], job_lease_token="wrong-worker"
            )
        assert exc.value.status_code == 409
    call.assert_called_once()


def test_execution_turns_persist_and_rerun_reuses_payment_and_completion_count(
    client, monkeypatch
):
    task = paid_task(client)
    running = state(requirements=requirements(web=False, code=True), steps=1)
    running["trace"] = [
        {
            "id": "one",
            "tool": "run_code",
            "status": "succeeded",
            "input": {},
            "output": {},
        }
    ]
    completed = deepcopy(running)
    completed.update(
        status="completed",
        report="Verified computed result " * 10,
        validation={"passed": True},
    )
    responses = iter([running, completed, completed])
    monkeypatch.setattr(
        "app.agents.call_bidders", lambda _: {"execution_state": next(responses)}
    )
    with session_factory()() as db:
        first = advance_execution(db, "demo-user", task["id"])
        assert first["status"] == "executing" and first["execution"]["steps"] == 1
        assert first["execution"]["trace"][0]["tool"] == "run_code"
    with session_factory()() as db:
        done = claim_delivery(db, task["id"])
        assert done["status"] == "completed"
        assert db.get(Agent, "finley").completed_tasks == 1
        original_payment = done["payment"]["id"]
        rerun_execution(db, "demo-user", task["id"])
    with session_factory()() as db:
        rerun = claim_delivery(db, task["id"])
        assert rerun["status"] == "completed"
        assert rerun["payment"]["id"] == original_payment
        assert db.scalar(select(func.count()).select_from(Payment)) == 1
        assert db.get(Agent, "finley").completed_tasks == 1
        assert db.scalar(select(func.count()).select_from(ExecutionRun)) == 2


def test_artifact_download_respects_task_ownership(client):
    task = paid_task(client)
    with session_factory()() as db:
        run = ExecutionRun(
            task_id=task["id"],
            state={"artifacts": [tools.artifact("result.csv", "a,b\n1,2")]},
        )
        db.add(run)
        db.commit()
        run_id = run.id
    url = f"/api/tasks/{task['id']}/artifacts/{run_id}/result.csv"
    assert client.get(url).json()["content"] == "a,b\n1,2"
    from app.auth import current_user
    from app.main import app

    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="other-account")
    assert client.get(url).status_code == 404
