from __future__ import annotations

from story_patterns.catalog.branches import effective_parents, group_versions


def _relation(previous: dict, current: dict) -> str:
    if len(effective_parents(current)) > 1:
        return "merge"
    if previous["branch"] != current["branch"]:
        return "fork"
    return "linear"


def compare_revisions(stories: list[dict]) -> list[dict]:
    """沿目录记录的父修订边比较版本，分叉与汇合各自成对出现，不按序号假设线性历史。"""
    grouped = group_versions(stories)
    changes = []
    for story_id, versions in sorted(grouped.items()):
        for revision in sorted(versions):
            current = versions[revision]
            for parent_revision in effective_parents(current):
                previous = versions.get(parent_revision)
                if previous is None:
                    continue
                previous_characters = {item["character_id"]: item for item in previous["characters"]}
                current_characters = {item["character_id"]: item for item in current["characters"]}
                previous_events = {item["event_id"]: item for item in previous["events"]}
                current_events = {item["event_id"]: item for item in current["events"]}
                shared_events = previous_events.keys() & current_events.keys()
                changes.append({
                    "story_id": story_id,
                    "from_revision": previous["revision"], "to_revision": current["revision"],
                    "from_branch": previous["branch"], "to_branch": current["branch"],
                    "relation": _relation(previous, current),
                    "title_changed": previous["title"] != current["title"],
                    "tradition_changed": previous["tradition"] != current["tradition"],
                    "source_changed": previous["source"] != current["source"],
                    "characters_added": sorted(current_characters.keys() - previous_characters.keys()),
                    "characters_removed": sorted(previous_characters.keys() - current_characters.keys()),
                    "sibling_orders_changed": sorted(
                        key for key in previous_characters.keys() & current_characters.keys()
                        if previous_characters[key]["sibling_order"] != current_characters[key]["sibling_order"]
                    ),
                    "events_added": sorted(current_events.keys() - previous_events.keys()),
                    "events_removed": sorted(previous_events.keys() - current_events.keys()),
                    "event_content_changed": sorted(
                        event_id for event_id in shared_events
                        if previous_events[event_id] != current_events[event_id]
                    ),
                    "requires_separate_review": True,
                })
    return changes
