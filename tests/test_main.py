from argparse import Namespace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from overleaf_to_git.__main__ import select_indices
from overleaf_to_git.overleaf_browser import get_project_updates, get_zip_package


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


class ArchiveCacheTests(TestCase):
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
