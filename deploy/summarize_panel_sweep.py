"""Render a panel sweep report as a GitHub step summary.

Separate from the workflow because a Python heredoc nested inside a shell
heredoc inside YAML is three quoting layers deep and silently wrong in at
least one of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def render(report: Dict[str, Any]) -> List[str]:
    lines = ["### Panel sweep against production data", ""]
    lines.append(f"- Builder calls: **{report.get('checked', 0)}**")
    lines.append(
        f"- Result: **{'every builder answered' if report.get('ok') else 'FAILURES'}**"
    )
    for label, key in (
        ("Reaches the database but unclassified", "undeclared"),
        ("Exclusions naming functions that no longer exist", "stale_exclusions"),
    ):
        if report.get(key):
            lines.append(f"- {label}: {', '.join(report[key])}")

    failures = report.get("failures") or []
    if failures:
        lines += [
            "",
            "| Builder | Subject | Seconds | Rows | Problem |",
            "| --- | --- | --- | --- | --- |",
        ]
        for failure in failures:
            problem = "over budget" if failure.get("over_budget") else "raised"
            rows = failure.get("rows")
            lines.append(
                f"| `{failure['builder']}` | {failure['subject']} "
                f"| {failure['seconds']} | {rows if rows is not None else '-'} | {problem} |"
            )

    slowest = report.get("slowest") or []
    if slowest:
        lines += [
            "",
            "<details><summary>Slowest ten</summary>",
            "",
            "| Builder | Subject | Seconds | Rows |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| `{row['builder']}` | {row['subject']} | {row['seconds']} "
            f"| {row.get('rows') if row.get('rows') is not None else '-'} |"
            for row in slowest
        ]
        lines += ["", "</details>"]
    return lines


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: summarize_panel_sweep.py <report.json>", file=sys.stderr)
        return 64

    path = Path(sys.argv[1])
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # An unreadable report means the sweep died before writing one. Saying
        # so beats an empty summary that reads like a pass.
        print("### Panel sweep against production data")
        print()
        print("The sweep produced no readable report; see the step log.")
        return 0

    print("\n".join(render(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
