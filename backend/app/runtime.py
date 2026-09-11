"""AgentCore HTTP contract: ARM64, port 8080, POST /invocations and GET /ping."""

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.agents import run_bidders
from app.config import get_settings
from app.db import session_factory
from app.service import dispatch

app = FastAPI(title="Marketplace AgentCore Runtime")


class Invocation(BaseModel):
    action: str
    user_id: str | None = None
    task_id: str | None = None
    data: dict = Field(default_factory=dict)
    task: dict | None = None
    agent: dict | None = None
    agents: list[dict] | None = None
    execution_state: dict | None = None
    requirements: dict | None = None


@app.get("/ping")
def ping():
    return {"status": "Healthy"}


@app.post("/invocations")
def invoke(body: Invocation):
    try:
        if get_settings().runtime_role == "bidders":
            return run_bidders(body.model_dump(exclude_none=True))
        with session_factory()() as db:
            if body.action == "advance_automation":
                from app.automation import advance_automation

                return advance_automation(db)
            return dispatch(db, body.user_id, body.action, body.data, body.task_id)
    except HTTPException as exc:
        return {"error": exc.detail, "status_code": exc.status_code}
    except ValidationError:
        return {"error": "Invalid marketplace request", "status_code": 422}
    except Exception as exc:
        logging.getLogger("runtime").error("Invocation failed (%s)", type(exc).__name__)
        return {"error": "Runtime could not complete the request", "status_code": 502}
