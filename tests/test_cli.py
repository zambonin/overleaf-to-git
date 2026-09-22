from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import requests

from overleaf_to_git.__main__ import main, parse_args, select_indices, summarize
from overleaf_to_git.custom_types import ArchiveResult, OverleafTag
from overleaf_to_git.data_composer import (
    create_sequences,
    display_projects,
    match_tags,
)


class SelectionTests(TestCase):
    def args(self, **overrides):
        values = {
            "project_ids": None,
            "projects": None,
            "tags": None,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_selects_stable_project_ids_in_dashboard_order(self):
        projects = [{"id": "first"}, {"id": "second"}, {"id": "third"}]

        selected = select_indices(
            self.args(project_ids=["third", "first"]), projects, []
        )

        self.assertEqual(selected, [1, 3])

    def test_unions_and_deduplicates_selection_methods(self):
        projects = [{"id": name} for name in ("first", "second", "third")]
        tags = [OverleafTag("tag", "Starred", frozenset({"third"}))]

        selected = select_indices(
            self.args(project_ids=["second"], projects="1-2", tags=["starred"]),
            projects,
            tags,
        )

        self.assertEqual(selected, [1, 2, 3])

    def test_rejects_unknown_project_id(self):
        with self.assertRaisesRegex(SystemExit, "unknown"):
            select_indices(self.args(project_ids=["unknown"]), [{"id": "known"}], [])

    def test_rejects_unknown_tag_and_lists_available_tags(self):
        tags = [OverleafTag("tag", "Available", frozenset())]

        with self.assertRaisesRegex(SystemExit, "Available"):
            match_tags([], tags, ["missing"])

    def test_sequence_parser_normalizes_ranges(self):
        self.assertEqual(create_sequences("7 2-4 4-2"), [2, 3, 4, 7])

    def test_sequence_parser_rejects_malformed_input(self):
        for value in ("", "0", "word", "1-", "1--2", "1-2-3"):
            with self.subTest(value=value):
                self.assertEqual(create_sequences(value), [])


class CliOutputTests(TestCase):
    def test_project_table_indices_follow_display_order(self):
        projects = [
            {
                "id": "new",
                "name": "Newest",
                "owner": {"email": "new@example.com"},
                "lastUpdated": "2026-09-22T12:00:00Z",
            },
            {
                "id": "old",
                "name": "Oldest",
                "owner": {"email": "old@example.com"},
                "lastUpdated": "2020-01-01T12:00:00Z",
            },
        ]

        table = display_projects(projects)

        self.assertLess(table.index("Newest"), table.index("Oldest"))
        self.assertIn("   1  Newest", table)
        self.assertIn("   2  Oldest", table)

    def test_rejects_invalid_network_budgets(self):
        invalid = (
            ("--timeout", "0"),
            ("--timeout", "nan"),
            ("--retries", "-1"),
        )
        for option, value in invalid:
            with (
                self.subTest(option=option),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                parse_args([option, value])

    def test_network_failure_has_no_traceback(self):
        with (
            patch(
                "overleaf_to_git.__main__.archive",
                side_effect=requests.ConnectionError("connection lost"),
            ),
            self.assertRaisesRegex(
                SystemExit, "Overleaf request failed: connection lost"
            ),
        ):
            main([])

    def test_summary_omits_unchanged_projects(self):
        results = [
            ("unchanged", ArchiveResult(Path("/tmp/unchanged"))),
            ("updated", ArchiveResult(Path("/tmp/updated"), added=2)),
        ]
        output = StringIO()

        with redirect_stdout(output):
            summarize(results)

        self.assertIn("2 projects, 1 updated:", output.getvalue())
        self.assertIn("/tmp/updated", output.getvalue())
        self.assertNotIn("/tmp/unchanged", output.getvalue())
