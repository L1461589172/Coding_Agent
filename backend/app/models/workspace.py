from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=4096)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("Workspace path is invalid")
        return normalized


class WorkspaceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=4096)
    path: str = Field(min_length=1, max_length=4096)


class WorkspaceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: WorkspaceInfo
    recent: list[WorkspaceInfo] = Field(max_length=10)
