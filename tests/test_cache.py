from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zipfile import BadZipFile, ZipFile

from overleaf_to_git.overleaf_browser import get_single_diff, get_zip_package


def zip_payload():
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("paper.tex", "content")
    return payload.getvalue()


class ZipCacheTests(TestCase):
    def test_zip_is_validated_before_it_becomes_a_cache_entry(self):
        with TemporaryDirectory() as directory:
            client = SimpleNamespace(cache_dir=Path(directory))

            with (
                patch(
                    "overleaf_to_git.overleaf_browser.get_zip_package_remote",
                    return_value=zip_payload(),
                ),
                get_zip_package(client, "project", 7) as archive,
            ):
                self.assertEqual(archive.read("paper.tex"), b"content")

            self.assertTrue((Path(directory) / "project" / "7.zip").is_file())

    def test_corrupt_zip_is_removed_instead_of_becoming_a_cache_entry(self):
        with TemporaryDirectory() as directory:
            client = SimpleNamespace(cache_dir=Path(directory))
            cached = Path(directory) / "project" / "7.zip"

            with (
                patch(
                    "overleaf_to_git.overleaf_browser.get_zip_package_remote",
                    return_value=zip_payload(),
                ),
                patch.object(ZipFile, "testzip", return_value="paper.tex"),
                self.assertRaisesRegex(BadZipFile, "paper.tex"),
            ):
                get_zip_package(client, "project", 7)

            self.assertFalse(cached.exists())
            self.assertEqual(list(cached.parent.iterdir()), [])


class DiffCacheTests(TestCase):
    def test_cache_keys_do_not_alias_paths_and_cached_values_are_reused(self):
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
                cached = get_single_diff(client, "project", "a/b", 1, 2)

            self.assertEqual(nested["diff"][0]["i"], "a/b")
            self.assertEqual(dashed["diff"][0]["i"], "a-b")
            self.assertEqual(cached, nested)
            self.assertEqual(remote.call_count, 2)
