from dataclasses import dataclass, field
from math import isfinite
from os import environ
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workspace: Path
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = ""
    llm_timeout_seconds: float = 60.0
    llm_connect_timeout_seconds: float = 10.0
    llm_max_retries: int = 2
    context_max_characters: int = 80_000
    context_max_tokens: int = 20_000
    tool_result_max_characters: int = 12_000
    context_recent_rounds: int = 8
    event_max_payload_characters: int = 12_000
    event_max_history_characters: int = 256_000
    event_max_history_events: int = 512
    max_consecutive_llm_errors: int = 3
    max_consecutive_runtime_errors: int = 3
    max_consecutive_command_timeouts: int = 3
    max_steps: int = 20
    max_tasks: int = 100
    port: int = 8000

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tasks < 1:
            raise ValueError("max_steps and max_tasks must be positive")
        if (
            not isfinite(self.llm_timeout_seconds)
            or not isfinite(self.llm_connect_timeout_seconds)
            or self.llm_timeout_seconds <= 0
            or self.llm_connect_timeout_seconds <= 0
        ):
            raise ValueError("LLM timeouts must be positive")
        if not 0 <= self.llm_max_retries <= 10:
            raise ValueError("llm_max_retries must be between 0 and 10")
        if self.context_max_characters < 1 or self.context_max_tokens < 1:
            raise ValueError("Context character and token budgets must be positive")
        if self.tool_result_max_characters < 256:
            raise ValueError("tool_result_max_characters must be at least 256")
        if self.context_recent_rounds < 1:
            raise ValueError("context_recent_rounds must be positive")
        if self.event_max_payload_characters < 256:
            raise ValueError("event_max_payload_characters must be at least 256")
        if self.event_max_history_characters < self.event_max_payload_characters + 1_024:
            raise ValueError(
                "event_max_history_characters must cover one payload and its event envelope"
            )
        if self.event_max_history_events < 1:
            raise ValueError("event_max_history_events must be positive")
        if (
            min(
                self.max_consecutive_llm_errors,
                self.max_consecutive_runtime_errors,
                self.max_consecutive_command_timeouts,
            )
            < 1
        ):
            raise ValueError("Consecutive error thresholds must be positive")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")

    @classmethod
    def from_env(cls, workspace: str | None = None, port: int = 8000) -> "Settings":
        return cls(
            workspace=Path(workspace or environ.get("CODING_AGENT_WORKSPACE", ".")),
            api_key=environ.get("CODING_AGENT_API_KEY", ""),
            base_url=environ.get("CODING_AGENT_BASE_URL", ""),
            model=environ.get("CODING_AGENT_MODEL", ""),
            llm_timeout_seconds=float(environ.get("CODING_AGENT_LLM_TIMEOUT_SECONDS", "60")),
            llm_connect_timeout_seconds=float(
                environ.get("CODING_AGENT_LLM_CONNECT_TIMEOUT_SECONDS", "10")
            ),
            llm_max_retries=int(environ.get("CODING_AGENT_LLM_MAX_RETRIES", "2")),
            context_max_characters=int(environ.get("CODING_AGENT_CONTEXT_MAX_CHARACTERS", "80000")),
            context_max_tokens=int(environ.get("CODING_AGENT_CONTEXT_MAX_TOKENS", "20000")),
            tool_result_max_characters=int(
                environ.get("CODING_AGENT_TOOL_RESULT_MAX_CHARACTERS", "12000")
            ),
            context_recent_rounds=int(environ.get("CODING_AGENT_CONTEXT_RECENT_ROUNDS", "8")),
            event_max_payload_characters=int(
                environ.get("CODING_AGENT_EVENT_MAX_PAYLOAD_CHARACTERS", "12000")
            ),
            event_max_history_characters=int(
                environ.get("CODING_AGENT_EVENT_MAX_HISTORY_CHARACTERS", "256000")
            ),
            event_max_history_events=int(
                environ.get("CODING_AGENT_EVENT_MAX_HISTORY_EVENTS", "512")
            ),
            max_consecutive_llm_errors=int(
                environ.get("CODING_AGENT_MAX_CONSECUTIVE_LLM_ERRORS", "3")
            ),
            max_consecutive_runtime_errors=int(
                environ.get("CODING_AGENT_MAX_CONSECUTIVE_RUNTIME_ERRORS", "3")
            ),
            max_consecutive_command_timeouts=int(
                environ.get("CODING_AGENT_MAX_CONSECUTIVE_COMMAND_TIMEOUTS", "3")
            ),
            max_steps=int(environ.get("CODING_AGENT_MAX_STEPS", "20")),
            port=port,
        )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in sorted({5173, self.port})
        ]

    @property
    def model_configured(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip() and self.model.strip())
