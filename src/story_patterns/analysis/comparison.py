from __future__ import annotations

from collections import defaultdict

from story_patterns.analysis.report import build_report


def _branch_breakdown(cohort: list[dict], decisions: dict, minimum: int,
                      adjudications: dict | None) -> list[dict]:
    by_branch = defaultdict(list)
    for story in cohort:
        by_branch[story["branch"]].append(story)
    rows = []
    for branch in sorted(by_branch):
        subset = by_branch[branch]
        identities = {(item["story_id"], item["revision"]) for item in subset}
        subset_decisions = {identity: decisions.get(identity, []) for identity in identities}
        subset_adjudications = ({identity: adjudications.get(identity) for identity in identities}
                                if adjudications else None)
        summary = build_report(subset, subset_decisions, None, minimum, adjudications=subset_adjudications)
        rows.append({
            "branch": branch,
            "story_revisions": summary["population"]["story_revisions"],
            "pattern_consensus": summary["population"]["pattern_consensus"],
            "outcome_consensus": summary["population"]["outcome_consensus"],
            "pattern_counts": summary["pattern_counts"],
            "outcome_counts": summary["outcome_counts"],
            "pattern_coverage": summary["coverage"]["pattern"],
            "outcome_coverage": summary["coverage"]["outcome"],
        })
    return rows


def compare_traditions(stories: list[dict], decisions: dict, minimum: int, adjudications: dict | None = None,
                       branch: str | None = None) -> dict:
    if branch is not None:
        stories = [story for story in stories if story["branch"] == branch]
    grouped = defaultdict(list)
    for story in stories:
        grouped[story["tradition"]].append(story)
    rows = []
    for tradition in sorted(grouped):
        cohort = grouped[tradition]
        identities = {(item["story_id"], item["revision"]) for item in cohort}
        cohort_decisions = {identity: decisions.get(identity, []) for identity in identities}
        cohort_adjudications = {identity: adjudications.get(identity) for identity in identities} if adjudications else None
        summary = build_report(cohort, cohort_decisions, tradition, minimum,
                               adjudications=cohort_adjudications)
        pattern_denominator = summary["population"]["pattern_consensus"]
        outcome_denominator = summary["population"]["outcome_consensus"]
        final_pattern_denominator = sum(summary["final_pattern_counts"].values())
        final_outcome_denominator = sum(summary["final_outcome_counts"].values())
        rows.append({
            "tradition": tradition,
            "story_revisions": summary["population"]["story_revisions"],
            "pattern_consensus": pattern_denominator,
            "outcome_consensus": outcome_denominator,
            "pattern_counts": summary["pattern_counts"],
            "pattern_rates": {key: count / pattern_denominator for key, count in summary["pattern_counts"].items()}
            if pattern_denominator else {},
            "outcome_counts": summary["outcome_counts"],
            "outcome_rates": {key: count / outcome_denominator for key, count in summary["outcome_counts"].items()}
            if outcome_denominator else {},
            "pattern_coverage": summary["coverage"]["pattern"],
            "outcome_coverage": summary["coverage"]["outcome"],
            "final_pattern_counts": summary["final_pattern_counts"],
            "final_outcome_counts": summary["final_outcome_counts"],
            "final_pattern_rates": {
                key: count / final_pattern_denominator
                for key, count in summary["final_pattern_counts"].items()
            } if final_pattern_denominator else {},
            "final_outcome_rates": {
                key: count / final_outcome_denominator
                for key, count in summary["final_outcome_counts"].items()
            } if final_outcome_denominator else {},
            "branch_breakdown": _branch_breakdown(cohort, decisions, minimum, adjudications),
        })
    return {
        "method": "descriptive comparison of independently filtered cohorts",
        "minimum_reviewers": minimum,
        "branch_filter": branch,
        "groups": rows,
        "interpretation_limit": "Rates use consensus labels only; coverage and denominators must be reviewed before comparison.",
    }
