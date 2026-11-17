from __future__ import annotations

from story_patterns.catalog.branches import group_versions, story_structure


def revision_lineage(stories: list[dict]) -> list[dict]:
    grouped = group_versions(stories)
    result = []
    for story_id, versions in sorted(grouped.items()):
        ordered = [versions[revision] for revision in sorted(versions)]
        revision_numbers = [item["revision"] for item in ordered]
        expected = list(range(1, revision_numbers[-1] + 1))
        missing = sorted(set(expected) - set(revision_numbers))
        structure = story_structure(versions)
        result.append({
            "story_id": story_id,
            "revision_count": len(ordered),
            "latest_revision": revision_numbers[-1],
            "missing_revision_numbers": missing,
            "titles_by_revision": [{"revision": item["revision"], "title": item["title"],
                                    "branch": item["branch"]} for item in ordered],
            "traditions": sorted({item["tradition"] for item in ordered}),
            "branches": structure["branches"],
            "roots": structure["roots"],
            "forks": structure["forks"],
            "merges": structure["merges"],
        })
    return result


def lineage_warnings(lineage: list[dict]) -> list[dict]:
    return [{"story_id": item["story_id"], "missing_revision_numbers": item["missing_revision_numbers"]}
            for item in lineage if item["missing_revision_numbers"]]
