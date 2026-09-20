"""Pass-stage mapping (METHODOLOGY §4.4).

Loads ``configs/stage_map.yaml`` and maps a Qiskit module/path to a canonical
transpiler stage by longest-prefix match. Used both to classify executed passes
(by ``__module__``) and to compute ``change_stage_match`` (by changed file path).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

def _find_default_config() -> Path:
    """Walk upward from this file to find configs/stage_map.yaml (robust to depth)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "configs" / "stage_map.yaml"
        if candidate.exists():
            return candidate
    # Fallback to the conventional location even if missing (clear error on load).
    return here.parents[2] / "configs" / "stage_map.yaml"


_DEFAULT_CONFIG = _find_default_config()


def _normalize(path_or_module: str) -> str:
    """Normalize a dotted module or filesystem path to '/'-separated form."""
    s = path_or_module.replace("\\", "/")
    # Treat dotted module paths (no slash) as '/'-separated.
    if "/" not in s:
        s = s.replace(".", "/")
    return s


@dataclass(frozen=True)
class StageMap:
    prefixes: dict[str, str]
    default_stage: str
    canonical_stages: tuple[str, ...]
    qiskit_anchor: str | None = None

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "StageMap":
        path = Path(config_path) if config_path else _DEFAULT_CONFIG
        data = yaml.safe_load(path.read_text())
        return cls(
            prefixes={_normalize(k): v for k, v in data["prefixes"].items()},
            default_stage=data["default_stage"],
            canonical_stages=tuple(data["canonical_stages"]),
            qiskit_anchor=data.get("qiskit_anchor"),
        )

    def stage_for(self, path_or_module: str) -> str:
        """Return the canonical stage for a module/path via longest-prefix match."""
        s = _normalize(path_or_module)
        best, best_len = self.default_stage, -1
        for prefix, stage in self.prefixes.items():
            if s.startswith(prefix) and len(prefix) > best_len:
                best, best_len = stage, len(prefix)
        return best

    def is_broad(self, stage: str) -> bool:
        """Stages that route to the exploration reserve rather than one stage (§4.2)."""
        return stage in ("passmanager_global", "shared_utility_unknown")
