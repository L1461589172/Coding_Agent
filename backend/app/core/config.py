from dataclasses import dataclass, field
from os import environ
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workspace: Path
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = ""
    max_steps: int = 20
    max_tasks: int = 100
    port: int = 8000

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tasks < 1:
            raise ValueError("max_steps and max_tasks must be positive")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")

    @classmethod
    def from_env(cls, workspace: str | None = None, port: int = 8000) -> "Settings":
        return cls(
            workspace=Path(workspace or environ.get("CODING_AGENT_WORKSPACE", ".")),
            api_key=environ.get("CODING_AGENT_API_KEY", ""),
            base_url=environ.get("CODING_AGENT_BASE_URL", ""),
            model=environ.get("CODING_AGENT_MODEL", ""),
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
