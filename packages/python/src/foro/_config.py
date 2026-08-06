"""Where the CLI's credential lives, and which host it belongs to.

Split out from auth.py because storage is the fiddly half and every later
command that needs a token reads it the same way: one file per machine, keyed
by host so a self-hosted or native-dev instance can coexist with foro.sh, mode
0600 because it holds a bearer token, and `FORO_TOKEN` winning over the file
the way `GH_TOKEN` does for gh.
"""

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
    # `logout` can't delete what it didn't write and `status` has to say where
    # the token came from, or people wonder why logout changed nothing - so
    # the source travels with the credential.
    from_env: bool = False


def resolve_host() -> str:
    """`FORO_HOST` selects the instance; this is also how the flow gets tested
    against a native dev stack on localhost:3001."""
    return os.environ.get(ENV_HOST) or DEFAULT_HOST


def config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "foro" / "hosts.yml"


def has_insecure_permissions() -> bool:
    """A token file other users can read is worth warning about. Windows
    doesn't carry POSIX mode bits, so there is nothing to check there."""
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
    # Opened 0600 rather than written and then chmod'ed - the file holds a
    # bearer token and must never exist as world-readable, not even briefly.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        # os.open's mode applies only when it creates the file, so an already
        # existing hosts.yml kept whatever mode it had and a token went
        # straight into a world-readable file. Narrow it on the descriptor
        # we already hold rather than on the path: no window where the name
        # could be swapped for something else between the two calls.
        if os.name != "nt":
            os.fchmod(handle.fileno(), 0o600)
        yaml.safe_dump(hosts, handle, sort_keys=True)


def load(host: str) -> Credentials | None:
    """The environment wins over the file, and is never written back to it."""
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
        # Removing the file rather than leaving `{}` behind: logging out of the
        # last host should leave the machine as it was before the first login.
        config_path().unlink(missing_ok=True)
