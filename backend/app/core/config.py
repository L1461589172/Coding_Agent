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
