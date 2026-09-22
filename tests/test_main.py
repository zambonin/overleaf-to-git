from argparse import Namespace
from contextlib import redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import ClassVar
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

import pygit2
import requests

from overleaf_to_git.__main__ import main, parse_args, select_indices
from overleaf_to_git.custom_types import (
    OverleafProjectWithHistory,
    OverleafRevision,
    OverleafSingleRevision,
)
from overleaf_to_git.data_composer import display_projects
from overleaf_to_git.git_operations import create_repo
from overleaf_to_git.overleaf_browser import (
    get_project_updates,
    get_single_diff,
    get_zip_package,
    require_success,
)


class SelectIndicesTests(TestCase):
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

    def test_rejects_unknown_project_id(self):
        with self.assertRaisesRegex(SystemExit, "unknown"):
            select_indices(self.args(project_ids=["unknown"]), [{"id": "known"}], [])

    def test_project_table_is_newest_first_with_matching_indices(self):
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
        with patch(
            "overleaf_to_git.__main__.archive",
            side_effect=requests.ConnectionError("connection lost"),
        ):
            with self.assertRaisesRegex(
                SystemExit, "Overleaf request failed: connection lost"
            ):
                main([])


class ArchiveCacheTests(TestCase):
    def test_http_errors_have_a_concise_context(self):
        response = SimpleNamespace(status_code=503)

        with self.assertRaisesRegex(
            SystemExit, "Reading history failed \\(HTTP 503\\)"
        ):
            require_success(response, "Reading history")

    def test_history_forbidden_is_an_error(self):
        client = SimpleNamespace(
            get=lambda *args, **kwargs: SimpleNamespace(status_code=403)
        )

        with self.assertRaisesRegex(SystemExit, "HTTP 403"):
            get_project_updates(client, "project")

    def test_zip_is_validated_before_it_becomes_a_cache_entry(self):
        with TemporaryDirectory() as directory:
            client = SimpleNamespace(cache_dir=Path(directory))
            payload = BytesIO()
            with ZipFile(payload, "w") as archive:
                archive.writestr("paper.tex", "content")

            with patch(
                "overleaf_to_git.overleaf_browser.get_zip_package_remote",
                return_value=payload.getvalue(),
            ):
                with get_zip_package(client, "project", 7) as archive:
                    self.assertEqual(archive.read("paper.tex"), b"content")

            self.assertTrue((Path(directory) / "project" / "7.zip").is_file())

    def test_diff_cache_keys_do_not_alias_paths(self):
        with TemporaryDirectory() as directory:
            client = SimpleNamespace(cache_dir=Path(directory))

            def response(_client, _project, path, _old, _new):
                return {"diff": [{"i": path}]}

            with patch(
                "overleaf_to_git.overleaf_browser.get_single_diff_remote",
                side_effect=response,
            ) as remote:
                nested = get_single_diff(client, "project", "a/b", 1, 2)
                dashed = get_single_diff(client, "project", "a-b", 1, 2)

            self.assertEqual(nested["diff"][0]["i"], "a/b")
            self.assertEqual(dashed["diff"][0]["i"], "a-b")
            self.assertEqual(remote.call_count, 2)


class GitArchiveTests(TestCase):
    author: ClassVar[dict[str, str]] = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
    }

    def project(self, name="Notes"):
        revision = OverleafRevision(
            authors=[self.author],
            before_ts=1_700_000_000_000,
            after_ts=1_700_000_001_000,
            file_revs=[OverleafSingleRevision("paper.tex", 1, 2, "hello\n", "keep")],
        )
        return OverleafProjectWithHistory("abc123", name, [revision])

    def test_rerun_reproduces_the_same_commit(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = create_repo(self.project(), output)
            first_tip = pygit2.Repository(str(first.path)).head.target

            second = create_repo(self.project(), output)
            second_tip = pygit2.Repository(str(second.path)).head.target

            self.assertEqual(first.added, 1)
            self.assertEqual(second.added, 0)
            self.assertEqual(first_tip, second_tip)

    def test_dirty_repository_is_rejected_before_a_rename(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = create_repo(self.project(), output)
            (first.path / "paper.tex").write_text("local change\n")
            renamed = output / "abc123-Renamed"

            with self.assertRaisesRegex(SystemExit, "uncommitted changes"):
                create_repo(self.project("Renamed"), output)

            self.assertTrue(first.path.exists())
            self.assertFalse(renamed.exists())

    def test_unrelated_existing_path_is_not_modified(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            target = output / "abc123-Notes"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("mine\n")

            with self.assertRaisesRegex(SystemExit, "existing path"):
                create_repo(self.project(), output)

            self.assertEqual(marker.read_text(), "mine\n")
            self.assertFalse((target / ".git").exists())

    def test_local_commit_is_parked_before_the_archive_is_rebuilt(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = create_repo(self.project(), output)
            repo = pygit2.Repository(str(first.path))
            imported_tip = repo.head.target
            blob = repo.create_blob(b"local\n")
            index = repo.index
            index.add(pygit2.IndexEntry("local.txt", blob, 0o100644))
            tree = index.write_tree()
            signature = pygit2.Signature(
                "Local User", "local@example.com", 1_700_000_002, 0
            )
            local_tip = repo.create_commit(
                repo.head.name,
                signature,
                signature,
                "local work\n",
                tree,
                [imported_tip],
            )
            repo.reset(local_tip, pygit2.GIT_RESET_HARD)

            result = create_repo(self.project(), output)
            repo = pygit2.Repository(str(first.path))

            self.assertEqual(repo.head.target, imported_tip)
            self.assertIsNotNone(result.parked)
            self.assertEqual(repo.branches[result.parked].target, local_tip)
