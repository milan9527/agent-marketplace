from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal[
    "Finance", "Research", "Development", "Content", "Data", "Automation"
]
Money = Decimal


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskCreate(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    spec: str = Field(min_length=10, max_length=8000)
    category: Category
    budget: Money = Field(gt=0, le=100, decimal_places=6)
    deadline: datetime
    preferred_agent_id: str | None = None
    selection_mode: Literal["manual", "auto"] = "manual"
    agent_scope: Literal["all", "demo", "live"] = "all"

    @field_validator("deadline")
    @classmethod
    def future_deadline(cls, value):
        if value.tzinfo is None:
            raise ValueError("The deadline must include a timezone")
        if value <= datetime.now(timezone.utc):
            raise ValueError("The deadline must be in the future")
        return value


class AgentCreate(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    tagline: str = Field(min_length=5, max_length=180)
    description: str = Field(min_length=20, max_length=4000)
    category: Category
    skills: list[str] = Field(min_length=1, max_length=8)
    price: Money = Field(gt=0, le=100, decimal_places=6)
    wallet: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")

    @field_validator("wallet")
    @classmethod
    def nonzero_wallet(cls, value):
        if int(value, 16) == 0:
            raise ValueError("The recipient wallet cannot be the zero address")
        return value.lower()

    @field_validator("skills")
    @classmethod
    def valid_skills(cls, values):
        if any(not v.strip() or len(v) > 40 for v in values):
            raise ValueError("Each skill must contain 1–40 characters")
        return list(dict.fromkeys(v.strip() for v in values))


class Selection(StrictModel):
    bid_id: str


class Rating(StrictModel):
    score: int = Field(ge=1, le=5)


class BudgetUpdate(StrictModel):
    budget: Money = Field(gt=0, le=1000, decimal_places=6)


class WalletBind(StrictModel):
    pass


def micros(value: Decimal) -> int:
    return int(value * 1_000_000)


def money(value: int) -> str:
    return format(Decimal(value) / 1_000_000, ".6f")
