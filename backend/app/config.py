from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_mode: Literal["demo", "aws"] = "demo"
    database_url: str = "sqlite:///./marketplace.db"
    database_secret_arn: str = ""
    cors_origins: str = "http://localhost:5174,http://localhost:3000"
    aws_region: str = "us-west-2"
    orchestrator_runtime_arn: str = ""
    bidder_runtime_arn: str = ""
    runtime_role: Literal["orchestrator", "bidders"] = "orchestrator"
    bedrock_model_id: str = "us.amazon.nova-pro-v1:0"
    payment_manager_arn: str = ""
    payment_connector_id: str = ""
    payment_instrument_id: str = ""
    payment_user_id: str = ""
    payment_owner_sub: str = ""
    payment_delegate_sub: str = ""
    payment_delegate_limit_micros: int = Field(default=1_000_000, ge=0)
    showcase_user_sub: str = ""
    showcase_task_ids: str = ""
    showcase_agent_ids: str = ""
    privy_wallet_url: str = ""
    facilitator_url: str = "https://x402.org/facilitator"
    facilitator_token: str = ""
    cognito_issuer: str = ""
    cognito_client_id: str = ""
    cognito_domain: str = ""
    chain_network: Literal["eip155:84532"] = "eip155:84532"
    usdc_address: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

    def validate_api(self) -> None:
        if self.app_mode == "aws":
            for name in (
                "cognito_issuer",
                "cognito_client_id",
                "orchestrator_runtime_arn",
            ):
                if not getattr(self, name):
                    raise RuntimeError(f"{name} is required in AWS mode")


@lru_cache
def get_settings() -> Settings:
    return Settings()
