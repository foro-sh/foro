"""Pick a workspace by name or id. A token reaches every workspace its user
belongs to, so commands name the one they act in."""

from __future__ import annotations

from foro.auth import Workspace


class WorkspaceError(Exception):
    pass


def select(selector: str, workspaces: list[Workspace]) -> Workspace:
    for workspace in workspaces:
        if workspace.id == selector:
            return workspace
    matches = [w for w in workspaces if w.name.casefold() == selector.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise WorkspaceError(
            f"more than one workspace is called {selector!r} - use its id (`foro workspace list`)"
        )
    names = ", ".join(w.name for w in workspaces) or "none"
    raise WorkspaceError(f"no workspace {selector!r} - yours: {names}")
