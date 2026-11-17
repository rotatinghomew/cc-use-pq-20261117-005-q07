from __future__ import annotations

from collections import defaultdict


def effective_parents(story: dict) -> list[int]:
    """未显式声明 parents 时按线性默认取上一序号；显式空列表表示无父修订。"""
    parents = story.get("parents")
    if parents is not None:
        return list(parents)
    return [story["revision"] - 1] if story["revision"] > 1 else []


def group_versions(stories: list[dict]) -> dict[str, dict[int, dict]]:
    grouped: dict[str, dict[int, dict]] = defaultdict(dict)
    for story in stories:
        grouped[story["story_id"]][story["revision"]] = story
    return dict(grouped)


def _ancestors(versions: dict[int, dict], revision: int) -> set[int]:
    seen: set[int] = set()
    stack = list(effective_parents(versions[revision]))
    while stack:
        current = stack.pop()
        if current in seen or current not in versions:
            continue
        seen.add(current)
        stack.extend(effective_parents(versions[current]))
    return seen


def nearest_common_ancestors(versions: dict[int, dict], first: int, second: int) -> list[int]:
    """返回两个修订最近共同祖先；DAG 中可能不止一个，也可能没有。"""
    if first not in versions or second not in versions:
        return []
    shared = (_ancestors(versions, first) | {first}) & (_ancestors(versions, second) | {second})
    nearest = [candidate for candidate in shared
               if not any(candidate in _ancestors(versions, other) for other in shared if other != candidate)]
    return sorted(nearest)


def story_structure(versions: dict[int, dict]) -> dict:
    """由同一故事的各修订文档推导分支、分叉、汇合与分支末端。"""
    children: dict[int, list[int]] = defaultdict(list)
    branches: dict[str, list[int]] = defaultdict(list)
    for revision, story in versions.items():
        branches[story["branch"]].append(revision)
        for parent in effective_parents(story):
            children[parent].append(revision)
    forks = []
    for parent, offspring in sorted(children.items()):
        if len(offspring) > 1:
            forks.append({
                "revision": parent,
                "branch": versions[parent]["branch"] if parent in versions else None,
                "children": [{"revision": child, "branch": versions[child]["branch"]}
                             for child in sorted(offspring)],
            })
    merges = [{"revision": revision, "branch": story["branch"], "parents": effective_parents(story)}
              for revision, story in sorted(versions.items()) if len(effective_parents(story)) > 1]
    branch_rows = []
    for name, revisions in sorted(branches.items()):
        revisions = sorted(revisions)
        branch_rows.append({"branch": name, "revisions": revisions, "tip_revision": revisions[-1]})
    return {
        "branches": branch_rows,
        "roots": sorted(revision for revision, story in versions.items()
                        if not effective_parents(story)),
        "forks": forks,
        "merges": merges,
    }


def branch_tip_pairs(structure: dict) -> list[tuple[str, str, int, int]]:
    tips = [(row["branch"], row["tip_revision"]) for row in structure["branches"]]
    pairs = []
    for index, (first_branch, first_tip) in enumerate(tips):
        for other_branch, other_tip in tips[index + 1:]:
            pairs.append((first_branch, other_branch, first_tip, other_tip))
    return pairs


def latest_marks(marks: list[dict]) -> dict[tuple[str, str], dict]:
    """每个 (story_id, branch) 取序号最大的标记作为当前状态，旧标记仍保留在记录中。"""
    current: dict[tuple[str, str], dict] = {}
    for mark in marks:
        key = (mark["story_id"], mark["branch"])
        if key not in current or mark["sequence"] > current[key]["sequence"]:
            current[key] = mark
    return current


def build_branch_overview(stories: list[dict], marks: list[dict] | None = None) -> list[dict]:
    """汇总每个故事的分支结构、共同祖先与生命周期标记，供报告与 branches 命令共用。"""
    current_marks = latest_marks(marks or [])
    marks_by_story: dict[str, list[dict]] = defaultdict(list)
    for mark in marks or []:
        marks_by_story[mark["story_id"]].append(mark)
    overview = []
    for story_id, versions in sorted(group_versions(stories).items()):
        structure = story_structure(versions)
        for row in structure["branches"]:
            mark = current_marks.get((story_id, row["branch"]))
            row["status"] = mark["action"] if mark else "active"
            row["status_detail"] = (
                {"target_branch": mark["target_branch"], "merge_revision": mark["merge_revision"]}
                if mark and mark["action"] == "merged" else None
            )
        common_ancestors = []
        for first_branch, other_branch, first_tip, other_tip in branch_tip_pairs(structure):
            shared = nearest_common_ancestors(versions, first_tip, other_tip)
            common_ancestors.append({
                "branches": [first_branch, other_branch],
                "tip_revisions": [first_tip, other_tip],
                "nearest_common_ancestors": shared,
            })
        overview.append({
            "story_id": story_id,
            **structure,
            "common_ancestors": common_ancestors,
            "marks": [
                {"mark_id": mark["mark_id"], "branch": mark["branch"], "sequence": mark["sequence"],
                 "action": mark["action"], "target_branch": mark["target_branch"],
                 "merge_revision": mark["merge_revision"], "note": mark["note"],
                 "recorded_by": mark["recorded_by"]}
                for mark in sorted(marks_by_story.get(story_id, []),
                                   key=lambda item: (item["branch"], item["sequence"]))
            ],
        })
    return overview
