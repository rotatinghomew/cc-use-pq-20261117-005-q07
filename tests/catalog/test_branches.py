import unittest

from story_patterns.errors import ConflictError, NotFoundError, ValidationError
from tests.support import AppCase, batch, decision, story


def branched(story_id="tale-a", revision=2, branch="variant-a", parents=None, tradition="coast"):
    record = story(story_id, revision, tradition)
    record["branch"] = branch
    if parents is not None:
        record["parents"] = parents
    return record


def mark(story_id="tale-a", branch="variant-a", action="retired", mark_id="mark-1",
         sequence=1, target=None, merge_revision=None, note="no longer adopted"):
    record = {"mark_id": mark_id, "story_id": story_id, "branch": branch, "sequence": sequence,
              "action": action, "note": note, "recorded_by": "editor-1"}
    if target is not None:
        record["target_branch"] = target
    if merge_revision is not None:
        record["merge_revision"] = merge_revision
    return record


def import_fork(app, story_id="tale-a"):
    """r1 -> r2 (main)；r3、r4 从 r2 分叉到两支；r5 汇合两支。"""
    app.import_batch(batch([story(story_id, 1), story(story_id, 2)], "base"))
    variants = [branched(story_id, 3, "variant-a", [2]), branched(story_id, 4, "variant-b", [2])]
    app.import_batch(batch(variants, "variants"))
    return variants


class BranchRegistrationTests(AppCase, unittest.TestCase):
    def test_two_variants_share_a_common_parent_instead_of_a_fake_chain(self):
        self.import_story(story(revision=1), "rev1")
        self.import_story(story(revision=2), "rev2")
        import_fork(self.app)
        overview = self.app.branch_overview("tale-a")[0]
        self.assertEqual(overview["forks"], [{
            "revision": 2, "branch": "main",
            "children": [{"revision": 3, "branch": "variant-a"},
                         {"revision": 4, "branch": "variant-b"}],
        }])
        branches = {row["branch"]: row for row in overview["branches"]}
        self.assertEqual(branches["variant-a"]["tip_revision"], 3)
        self.assertEqual(branches["variant-b"]["tip_revision"], 4)
        self.assertEqual(branches["main"]["status"], "active")

    def test_tips_policy_lists_every_branch_tip_while_latest_keeps_only_one(self):
        import_fork(self.app)
        tips = self.app.search_stories(revision_policy="tips")
        self.assertEqual([(item["revision"], item["branch"]) for item in tips],
                         [(2, "main"), (3, "variant-a"), (4, "variant-b")])
        latest = self.app.search_stories(revision_policy="latest")
        self.assertEqual([(item["revision"], item["branch"]) for item in latest], [(4, "variant-b")])
        only_a = self.app.search_stories(branch="variant-a")
        self.assertEqual([item["revision"] for item in only_a], [3])

    def test_merge_revision_records_two_parents_and_common_ancestor(self):
        import_fork(self.app)
        merged = branched("tale-a", 5, "main", [3, 4])
        self.app.import_batch(batch([merged], "collation"))
        overview = self.app.branch_overview("tale-a")[0]
        self.assertEqual(overview["merges"], [{"revision": 5, "branch": "main", "parents": [3, 4]}])
        ancestors = {(tuple(pair["branches"])): pair["nearest_common_ancestors"]
                     for pair in overview["common_ancestors"]}
        self.assertEqual(ancestors[("variant-a", "variant-b")], [2])
        self.assertEqual(ancestors[("main", "variant-a")], [3])

    def test_revision_diffs_follow_edges_not_revision_order(self):
        import_fork(self.app)
        self.app.import_batch(batch([branched("tale-a", 5, "main", [3, 4])], "collation"))
        report = self.app.create_report()
        relations = {(change["from_revision"], change["to_revision"]): change["relation"]
                     for change in report["revision_changes"] if change["story_id"] == "tale-a"}
        self.assertEqual(relations[(1, 2)], "linear")
        self.assertEqual(relations[(2, 3)], "fork")
        self.assertEqual(relations[(2, 4)], "fork")
        self.assertEqual(relations[(3, 5)], "merge")
        self.assertEqual(relations[(4, 5)], "merge")
        self.assertNotIn((3, 4), relations)

    def test_linear_revisions_keep_default_parent_chain(self):
        self.app.import_batch(batch([story(revision=1), story(revision=2), story(revision=3)], "linear"))
        overview = self.app.branch_overview("tale-a")[0]
        self.assertEqual(overview["forks"], [])
        self.assertEqual(overview["merges"], [])
        self.assertEqual(overview["branches"],
                         [{"branch": "main", "revisions": [1, 2, 3], "tip_revision": 3,
                           "status": "active", "status_detail": None}])
        relations = [change["relation"] for change in self.app.create_report()["revision_changes"]]
        self.assertEqual(relations, ["linear", "linear"])

    def test_explicit_parents_must_exist_in_catalog_or_same_batch(self):
        self.import_story(story(revision=1), "rev1")
        dangling = branched("tale-a", 3, "variant-a", [2])
        with self.assertRaisesRegex(ValidationError, "missing parent 2"):
            self.app.import_batch(batch([dangling], "dangling"))
        self.assertEqual(self.app.catalog.list_stories(), [self.app.catalog.list_stories()[0]])
        within = [story("tale-b", 1), branched("tale-b", 2, "variant-a", [1])]
        result = self.app.import_batch(batch(within, "self-contained"))
        self.assertEqual(result["status"], "imported")

    def test_parent_declaration_shape_is_validated(self):
        for parents in [[0], [2, 2], [1, 5], "1", [True]]:
            with self.subTest(parents=parents):
                record = branched("tale-a", 3, "variant-a", parents)
                with self.assertRaises(ValidationError):
                    self.app.import_batch(batch([record], "bad-parents"))

    def test_implicit_parent_gap_is_backfilled_once_parent_arrives(self):
        self.app.import_batch(batch([story(revision=1), story(revision=3)], "sparse"))
        self.assertEqual(self.app.audit()["edges_checked"], 0)
        self.app.import_batch(batch([story(revision=2)], "filled"))
        audit = self.app.audit()
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["edges_checked"], 2)
        lineage = self.app.revision_lineage()[0]
        self.assertEqual(lineage["missing_revision_numbers"], [])


class BranchMarkTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import_fork(self.app)

    def test_retired_branch_stays_visible_with_auditable_note(self):
        self.app.record_branch_mark(mark())
        overview = self.app.branch_overview("tale-a")[0]
        status = {row["branch"]: row["status"] for row in overview["branches"]}
        self.assertEqual(status["variant-a"], "retired")
        self.assertEqual(overview["marks"][0]["note"], "no longer adopted")
        self.assertEqual(len(self.app.catalog.list_stories()), 4)
        report = self.app.create_report()
        self.assertEqual(report["population"]["story_revisions"], 4)
        self.assertTrue(self.app.audit()["ok"])

    def test_merged_mark_must_match_recorded_revision_structure(self):
        self.app.import_batch(batch([branched("tale-a", 5, "main", [3])], "collation"))
        result = self.app.record_branch_mark(
            mark(branch="variant-a", action="merged", target="main", merge_revision=5))
        self.assertEqual(result["status"], "recorded")
        not_an_input = mark(branch="variant-b", action="merged", target="main",
                            merge_revision=5, mark_id="mark-2")
        with self.assertRaisesRegex(ValidationError, "no parent on the marked branch"):
            self.app.record_branch_mark(not_an_input)
        wrong_target = mark(branch="variant-a", action="merged", target="variant-b",
                            merge_revision=5, mark_id="mark-3")
        with self.assertRaisesRegex(ValidationError, "target branch"):
            self.app.record_branch_mark(wrong_target)

    def test_mark_validation_rejects_unknowns_and_bad_shapes(self):
        with self.assertRaises(NotFoundError):
            self.app.record_branch_mark(mark(story_id="absent"))
        with self.assertRaisesRegex(ValidationError, "no recorded revision"):
            self.app.record_branch_mark(mark(branch="ghost"))
        with self.assertRaisesRegex(ValidationError, "retired or merged"):
            self.app.record_branch_mark(mark(action="archived"))
        with self.assertRaisesRegex(ValidationError, "cannot name a merge target"):
            self.app.record_branch_mark(mark(target="main", merge_revision=2))
        with self.assertRaisesRegex(ValidationError, "into itself"):
            self.app.record_branch_mark(mark(action="merged", target="variant-a", merge_revision=3))

    def test_mark_retry_is_idempotent_and_identifier_reuse_conflicts(self):
        record = mark()
        self.assertEqual(self.app.record_branch_mark(record)["status"], "recorded")
        self.assertEqual(self.app.record_branch_mark(record)["status"], "already_recorded")
        changed = mark(note="different note")
        with self.assertRaises(ConflictError):
            self.app.record_branch_mark(changed)
        self.assertEqual(len(self.app.store.branch_marks()), 1)

    def test_mark_sequence_collision_is_rejected(self):
        self.app.record_branch_mark(mark())
        with self.assertRaises(ConflictError):
            self.app.record_branch_mark(mark(mark_id="mark-2"))
        later = mark(mark_id="mark-2", sequence=2, action="merged", target="main", merge_revision=None)
        with self.assertRaisesRegex(ValidationError, "positive integer"):
            self.app.record_branch_mark(later)

    def test_audit_detects_tampered_edge_and_mark_without_deleting_history(self):
        self.app.record_branch_mark(mark())
        with self.app.store.transaction() as connection:
            connection.execute("UPDATE branch_marks SET note='forged'")
        result = self.app.audit()
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["scope"] == "branch_mark" for item in result["issues"]))
        with self.app.store.transaction() as connection:
            connection.execute("UPDATE branch_marks SET note='no longer adopted'")
            connection.execute("DELETE FROM revision_edges WHERE revision=3")
        result = self.app.audit()
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["scope"] == "edge" for item in result["issues"]))


class BranchAwareReviewTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import_fork(self.app)

    def test_decision_branch_label_is_cross_checked_when_provided(self):
        vote = decision(revision=3, annotator="reader-a")
        vote["branch"] = "variant-a"
        self.assertEqual(self.app.record_decision(vote)["status"], "recorded")
        wrong = decision(revision=3, annotator="reader-b")
        wrong["branch"] = "main"
        with self.assertRaisesRegex(ValidationError, "variant-a"):
            self.app.record_decision(wrong)
        unlabeled = decision(revision=3, annotator="reader-c")
        self.assertEqual(self.app.record_decision(unlabeled)["status"], "recorded")

    def test_adjudication_branch_label_is_cross_checked(self):
        record = {"adjudication_id": "adj-1", "story_id": "tale-a", "story_revision": 4,
                  "branch": "main", "moderator": "editor-1", "sequence": 1, "pattern": "harm",
                  "youngest_outcome": "loses", "evidence_event_ids": ["first"],
                  "rationale": "branch label must match the revision"}
        with self.assertRaisesRegex(ValidationError, "variant-b"):
            self.app.record_adjudication(record)
        record["branch"] = "variant-b"
        self.assertEqual(self.app.record_adjudication(record)["status"], "recorded")

    def test_queue_history_and_report_rows_all_carry_branch(self):
        self.app.record_decision(decision(revision=3, annotator="reader-a"))
        self.app.record_decision(decision(revision=3, annotator="reader-b"))
        queue = self.app.review_queue()
        by_revision = {row["revision"]: row["branch"] for row in queue["stories"]}
        self.assertEqual(by_revision, {1: "main", 2: "main", 3: "variant-a", 4: "variant-b"})
        history = self.app.review_history("tale-a", 3)
        self.assertEqual(history["branch"], "variant-a")
        report = self.app.create_report()
        rows = {row["revision"]: row["branch"] for row in report["story_results"]}
        self.assertEqual(rows[3], "variant-a")
        self.assertEqual(report["provenance"]["story_branches"]["tale-a@4"], "variant-b")

    def test_report_and_compare_can_be_scoped_to_one_branch(self):
        self.app.record_decision(decision(revision=3, annotator="reader-a"))
        self.app.record_decision(decision(revision=3, annotator="reader-b"))
        scoped = self.app.create_report(branch="variant-a")
        self.assertEqual(scoped["criteria"]["branch"], "variant-a")
        self.assertEqual(scoped["population"]["story_revisions"], 1)
        self.assertEqual(scoped["pattern_counts"], {"parallel": 1})
        comparison = self.app.compare_traditions()
        breakdown = comparison["groups"][0]["branch_breakdown"]
        self.assertEqual({row["branch"] for row in breakdown}, {"main", "variant-a", "variant-b"})
        filtered = self.app.compare_traditions(branch="variant-a")
        self.assertEqual(filtered["groups"][0]["story_revisions"], 1)

    def test_reimport_and_retry_do_not_duplicate_branches_or_judgments(self):
        variants = batch([branched("tale-a", 3, "variant-a", [2])], "variants-retry")
        self.assertEqual(self.app.import_batch(variants)["status"], "imported")
        self.assertEqual(self.app.import_batch(variants)["status"], "already_imported")
        vote = decision(revision=3, annotator="reader-a")
        self.app.record_decision(vote)
        self.assertEqual(self.app.record_decision(vote)["status"], "already_recorded")
        overview = self.app.branch_overview("tale-a")[0]
        self.assertEqual(len(overview["branches"]), 3)
        self.assertEqual(len(self.app.review.decisions_for("tale-a", 3)), 1)
        audit = self.app.audit()
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["edges_checked"], 3)


class BranchingDemoFixtureTests(AppCase, unittest.TestCase):
    def test_branching_fixture_presents_fork_merge_and_linear_history(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path

        from story_patterns.cli import main

        fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "branching.json"
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["demo", "--database", str(Path(directory) / "demo.sqlite3"),
                                  "--fixture", str(fixture_path)])
            self.assertEqual(exit_code, 0)
            output = json.loads(stdout.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as audit_out:
                audit_code = main(["audit", "--database", str(Path(directory) / "demo.sqlite3")])
            self.assertEqual(audit_code, 0)
            self.assertTrue(json.loads(audit_out.getvalue())["ok"])
        self.assertEqual([item["status"] for item in output["imports"]], ["imported"] * 3)
        self.assertEqual(output["retry_checks"]["import"]["status"], "already_imported")
        self.assertEqual(output["retry_checks"]["decision"]["status"], "already_recorded")
        report = output["report"]
        structure = {item["story_id"]: item for item in report["branch_structure"]}
        reed = structure["reed-sisters"]
        self.assertEqual([fork["revision"] for fork in reed["forks"]], [2])
        self.assertEqual(reed["merges"], [{"revision": 5, "branch": "main", "parents": [3, 4]}])
        ancestors = {tuple(pair["branches"]): pair["nearest_common_ancestors"]
                     for pair in reed["common_ancestors"]}
        self.assertEqual(ancestors[("north_variant", "south_variant")], [2])
        status = {row["branch"]: row["status"] for row in reed["branches"]}
        self.assertEqual(status, {"main": "active", "north_variant": "merged",
                                  "south_variant": "merged", "fragment_variant": "retired"})
        self.assertEqual(structure["mill-road"]["forks"], [])
        south = [row for row in report["story_results"] if row["revision"] == 4][0]
        self.assertEqual((south["branch"], south["resolution"]), ("south_variant", "adjudicated"))
        self.assertEqual(report["pattern_counts"], {"harm": 1, "parallel": 3})


if __name__ == "__main__":
    unittest.main()
