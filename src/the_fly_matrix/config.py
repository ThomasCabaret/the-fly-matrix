from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class NeuprintSettings:
    server: str
    dataset: str
    token: str

    @classmethod
    def from_project_env(cls, path: Path | None = None) -> "NeuprintSettings":
        values = read_env_file(path or ROOT / ".env")
        settings = cls(
            server=values.get("NEUPRINT_SERVER", "https://neuprint.janelia.org"),
            dataset=values.get("NEUPRINT_DATASET", "male-cns:v1.0"),
            token=values.get("NEUPRINT_APPLICATION_CREDENTIALS", ""),
        )
        if not settings.token:
            raise RuntimeError("NEUPRINT_APPLICATION_CREDENTIALS est absent ou vide dans .env")
        return settings
