"""Summarise a built data.json for the deploy workflow: which sources failed to update.

``python -m whips.report new/data.json [previous/data.json]`` prints a Markdown list of failed sources, and of
figures that vanished or lost many seats since the previous data (nothing when all is well) and exits 0 either way; the workflow turns the output into an alert.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def failed_sources(data: dict) -> list[dict]:
    return [s for s in data.get("sources", []) if s.get("status") != "ok"]


def lost_data(new: dict, old: dict, drop: float = 0.2) -> list[str]:
    """Figures that vanished, or lost more than ``drop`` of their seats, since the previously published data:
    the sign of a source that "succeeded" but returned little or nothing."""
    now = {m["id"]: m for m in new.get("metrics", [])}
    out = []
    for m in old.get("metrics", []):
        cur = now.get(m["id"])
        if cur is None:
            out.append(f"- **{m['label']}** (`{m['id']}`, {m.get('source', '')}) is no longer produced")
        elif m.get("coverage") and cur.get("coverage", 0) < (1 - drop) * m["coverage"]:
            out.append(f"- **{m['label']}** (`{m['id']}`) covers {cur.get('coverage', 0)} seats, down from {m['coverage']}")
    return out


def markdown(failed: list[dict]) -> str:
    return "\n".join(f"- **{s['name']}** (`{s['id']}`): {s.get('detail') or 'no detail'}" for s in failed)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    new = json.loads(Path(args[0]).read_text())
    lines = [markdown(failed_sources(new))]
    if len(args) > 1 and Path(args[1]).exists():
        try:
            lost = lost_data(new, json.loads(Path(args[1]).read_text()))
        except (ValueError, KeyError):  # no usable previous data: nothing to compare with
            lost = []
        if lost:
            lines.append("Figures that lost data since the last published version:\n" + "\n".join(lost))
    out = "\n\n".join(x for x in lines if x)
    if out:
        print(out)


if __name__ == "__main__":
    main()
