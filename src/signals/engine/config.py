"""Engine runtime configuration (env + HOCON-friendly defaults)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from signals.engine.k8s_apply import ApplyConfig


@dataclass(frozen=True)
class EngineConfig:
    """Lattice + YuniKorn + projection paths."""

    bind_host: str = "0.0.0.0"
    bind_port: int = 50551
    # Loopback control HTTP for lab attach (not the lattice, not C2).
    control_host: str = "127.0.0.1"
    control_port: int = 50552
    project: str = "signals"
    yk_rest_url: str = "http://127.0.0.1:30080"
    projection_root: Path = Path("build/dev")
    yk_request_timeout_s: float = 15.0
    apply: ApplyConfig = field(default_factory=ApplyConfig)

    @classmethod
    def from_env(cls) -> "EngineConfig":
        root = os.environ.get("SIGNALS_YK_PROJECTION_ROOT") or os.environ.get(
            "SIGNALS_ENGINE_PROJECTION_ROOT"
        )
        if root:
            proj = Path(root)
        else:
            data = os.environ.get("SIGNALS_DATA_ROOT")
            if data:
                proj = Path(data) / "engine" / "dev"
            else:
                # repo-local default (gitignored under build/)
                proj = Path(
                    os.environ.get("SIGNALS_REPO_ROOT", os.getcwd())
                ) / "build" / "dev"

        return cls(
            bind_host=os.environ.get("SIGNALS_ENGINE_BIND_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("SIGNALS_ENGINE_GRPC_PORT", "50551")),
            control_host=os.environ.get("SIGNALS_ENGINE_CONTROL_HOST", "127.0.0.1"),
            control_port=int(os.environ.get("SIGNALS_ENGINE_CONTROL_PORT", "50552")),
            project=os.environ.get("SIGNALS_ENGINE_PROJECT", "signals"),
            yk_rest_url=os.environ.get(
                "SIGNALS_YK_API_URL", "http://127.0.0.1:30080"
            ).rstrip("/"),
            projection_root=proj,
            yk_request_timeout_s=float(
                os.environ.get("SIGNALS_YK_TIMEOUT_S", "15")
            ),
            apply=ApplyConfig.from_env(),
        )

    @property
    def listen_addr(self) -> str:
        return f"{self.bind_host}:{self.bind_port}"

    @property
    def control_addr(self) -> str:
        return f"{self.control_host}:{self.control_port}"
