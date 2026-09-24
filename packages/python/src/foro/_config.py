"""Per-host credential file. FORO_TOKEN overrides the file."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_HOST = "foro.sh"
ENV_TOKEN = "FORO_TOKEN"
ENV_HOST = "FORO_HOST"


@dataclass
class Credentials:
    token: str
    user: str | None = None
    workspace: str | None = None
    from_env: bool = False


def resolve_host() -> str:
    return os.environ.get(ENV_HOST) or DEFAULT_HOST


def config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "foro" / "hosts.yml"


def has_insecure_permissions() -> bool:
    path = config_path()
    if os.name == "nt" or not path.exists():
        return False
    return bool(path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))


def _read_all() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _write_all(hosts: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create at 0600. os.open's mode applies only on create, so fchmod the
    # descriptor in case the file already existed with a wider mode.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        if os.name != "nt":
            os.fchmod(handle.fileno(), 0o600)
        yaml.safe_dump(hosts, handle, sort_keys=True)


def load(host: str) -> Credentials | None:
    env_token = os.environ.get(ENV_TOKEN)
    if env_token:
        return Credentials(token=env_token, from_env=True)

    entry = _read_all().get(host)
    if not entry or not entry.get("token"):
        return None
    return Credentials(
        token=entry["token"],
        user=entry.get("user"),
        workspace=entry.get("workspace"),
    )


def save(host: str, creds: Credentials) -> None:
    hosts = _read_all()
    hosts[host] = {
        "token": creds.token,
        "user": creds.user,
        "workspace": creds.workspace,
    }
    _write_all(hosts)


def delete(host: str) -> None:
    hosts = _read_all()
    if hosts.pop(host, None) is None:
        return
    if hosts:
        _write_all(hosts)
    else:
        config_path().unlink(missing_ok=True)
