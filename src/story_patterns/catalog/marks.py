from __future__ import annotations

from story_patterns.catalog.branches import effective_parents
from story_patterns.catalog.validate import digest_json, _text
from story_patterns.errors import ConflictError, NotFoundError, ValidationError

ACTIONS = {"retired", "merged"}


def normalize_branch_mark(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("branch mark must be an object")
    mark_id = _text(raw.get("mark_id"), "mark_id", 120)
    story_id = _text(raw.get("story_id"), "story_id", 100)
    branch = _text(raw.get("branch"), "branch", 60)
    sequence = raw.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise ValidationError("sequence must be a positive integer")
    action = raw.get("action")
    if action not in ACTIONS:
        raise ValidationError("action must be retired or merged")
    target_branch = raw.get("target_branch")
    merge_revision = raw.get("merge_revision")
    if action == "merged":
        target_branch = _text(target_branch, "target_branch", 60)
        if target_branch == branch:
            raise ValidationError("a branch cannot be merged into itself")
        if type(merge_revision) is not int or merge_revision < 1:
            raise ValidationError("merge_revision must be a positive integer")
    else:
        if target_branch is not None or merge_revision is not None:
            raise ValidationError("a retired mark cannot name a merge target")
        target_branch = None
        merge_revision = None
    note = raw.get("note", "")
    if not isinstance(note, str) or len(note) > 500:
        raise ValidationError("note must be text of at most 500 characters")
    recorded_by = _text(raw.get("recorded_by"), "recorded_by", 120)
    return {
        "mark_id": mark_id,
        "story_id": story_id,
        "branch": branch,
        "sequence": sequence,
        "action": action,
        "target_branch": target_branch,
        "merge_revision": merge_revision,
        "note": note.strip(),
        "recorded_by": recorded_by,
    }


def check_mark_against_structure(mark: dict, versions: dict[int, dict]) -> None:
    """确认标记与目录中不可变的修订结构一致，防止用标记伪造历史。"""
    branches = {story["branch"] for story in versions.values()}
    if mark["branch"] not in branches:
        raise ValidationError(f"branch {mark['branch']!r} has no recorded revision for this story")
    if mark["action"] != "merged":
        return
    merge = versions.get(mark["merge_revision"])
    if merge is None:
        raise ValidationError("merge_revision does not exist for this story")
    if merge["branch"] != mark["target_branch"]:
        raise ValidationError("merge_revision is not recorded on the target branch")
    merged_inputs = {versions[parent]["branch"] for parent in effective_parents(merge) if parent in versions}
    if mark["branch"] not in merged_inputs:
        raise ValidationError("merge_revision has no parent on the marked branch")


class BranchMarkService:
    def __init__(self, store):
        self.store = store

    def record(self, raw: dict) -> dict:
        story_id = raw.get("story_id") if isinstance(raw, dict) else None
        versions = self.store.story_versions(story_id) if isinstance(story_id, str) else {}
        if not versions:
            raise NotFoundError(f"story {story_id!r} was not found")
        mark = normalize_branch_mark(raw)
        check_mark_against_structure(mark, versions)
        digest = digest_json(mark)
        with self.store.transaction() as connection:
            previous = connection.execute(
                "SELECT digest FROM branch_marks WHERE mark_id = ?", (mark["mark_id"],)
            ).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise ConflictError(f"branch mark {mark['mark_id']} already identifies different content")
                return {"mark_id": mark["mark_id"], "status": "already_recorded"}
            occupied = connection.execute(
                "SELECT mark_id FROM branch_marks WHERE story_id=? AND branch=? AND sequence=?",
                (mark["story_id"], mark["branch"], mark["sequence"]),
            ).fetchone()
            if occupied:
                raise ConflictError("branch mark sequence is already occupied for this branch")
            connection.execute(
                "INSERT INTO branch_marks(mark_id, story_id, branch, sequence, action, target_branch, "
                "merge_revision, note, recorded_by, digest) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (mark["mark_id"], mark["story_id"], mark["branch"], mark["sequence"], mark["action"],
                 mark["target_branch"], mark["merge_revision"], mark["note"], mark["recorded_by"], digest),
            )
        return {"mark_id": mark["mark_id"], "status": "recorded"}
