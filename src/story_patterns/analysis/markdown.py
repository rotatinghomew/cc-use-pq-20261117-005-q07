from __future__ import annotations

import json


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> list[str]:
    headings = [label for _, label in columns]
    lines = ["| " + " | ".join(headings) + " |", "| " + " | ".join("---" for _ in headings) + " |"]
    for row in rows:
        cells = [str(row.get(key, "" )).replace("|", "\\|").replace("\n", " ") for key, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_report(report: dict) -> str:
    population = report["population"]
    criteria = report["criteria"]
    lines = [
        f"# Narrative analysis report {report['report_id']}", "",
        "This report summarizes annotated local records. It does not make literary claims on its own.", "",
        "## Scope", "",
        f"- Tradition filter: {criteria['tradition'] or 'all'}",
        f"- Branch filter: {criteria.get('branch') or 'all'}",
        f"- Minimum independent readers: {criteria['minimum_reviewers']}",
        f"- Story revisions: {population['story_revisions']}",
        f"- Pattern consensus: {population['pattern_consensus']}",
        f"- Outcome consensus: {population['outcome_consensus']}", "",
        "## Independent-reader consensus counts", "",
    ]
    lines.extend(_table([{"pattern": key, "count": value} for key, value in report["pattern_counts"].items()],
                        [("pattern", "Pattern"), ("count", "Stories")]))
    lines.extend(["", "## Final pattern counts", ""])
    lines.extend(_table([{"pattern": key, "count": value}
                         for key, value in report["final_pattern_counts"].items()],
                        [("pattern", "Pattern"), ("count", "Stories")]))
    lines.extend(["", "## Coverage", "", "Status counts retain unresolved records in the denominator.", ""])
    coverage = report["coverage"]["pattern"]
    lines.extend(_table([{"status": key, "count": value} for key, value in coverage.items()],
                        [("status", "Pattern review status"), ("count", "Stories")]))
    lines.extend(["", "## Branch structure", "",
                  "Branches, forks, merges, and common ancestors recorded in the catalog; "
                  "retired or merged branches remain listed for audit.", ""])
    for story in report.get("branch_structure", []):
        lines.append(f"### {story['story_id']}")
        lines.append("")
        branch_rows = [{"branch": row["branch"], "tip": row["tip_revision"], "status": row["status"],
                        "revisions": ",".join(str(revision) for revision in row["revisions"])}
                       for row in story["branches"]]
        lines.extend(_table(branch_rows, [("branch", "Branch"), ("revisions", "Revisions"),
                                          ("tip", "Tip"), ("status", "Status")]))
        lines.append("")
        for fork in story["forks"]:
            children = ", ".join(f"r{item['revision']} ({item['branch']})" for item in fork["children"])
            lines.append(f"- Fork after r{fork['revision']} ({fork['branch']}): {children}")
        for merge in story["merges"]:
            parents = ", ".join(f"r{parent}" for parent in merge["parents"])
            lines.append(f"- Merge at r{merge['revision']} ({merge['branch']}) from {parents}")
        for pair in story["common_ancestors"]:
            shared = ", ".join(f"r{revision}" for revision in pair["nearest_common_ancestors"]) or "none"
            first, second = pair["branches"]
            lines.append(f"- Nearest common ancestor of {first} and {second}: {shared}")
        for mark in story["marks"]:
            target = (f" into {mark['target_branch']} at r{mark['merge_revision']}"
                      if mark["action"] == "merged" else "")
            lines.append(f"- Mark {mark['mark_id']}: {mark['branch']} {mark['action']}{target} — "
                         f"{mark['note']} ({mark['recorded_by']})")
        lines.append("")
    lines.extend(["## Provenance", "", "Story revisions and decision IDs used:", "",
                  "```json", json.dumps(report["provenance"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)
