from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import pygit2

from overleaf_to_git.git_operations import create_repo

from .helpers import project


class GitSafetyTests(TestCase):
    def test_dirty_repository_is_rejected_before_a_rename(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = create_repo(project(), output)
            (first.path / "paper.tex").write_text("local change\n")
            renamed = output / "abc123-Renamed"

            with self.assertRaisesRegex(SystemExit, "uncommitted changes"):
                create_repo(project("Renamed"), output)

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
                create_repo(project(), output)

            self.assertEqual(marker.read_text(), "mine\n")
            self.assertFalse((target / ".git").exists())

    def test_project_rename_moves_the_repository(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = create_repo(project(), output)

            with patch("overleaf_to_git.git_operations.STATUS.note") as note:
                renamed = create_repo(project("Renamed"), output)

            self.assertFalse(first.path.exists())
            self.assertEqual(renamed.path, output / "abc123-Renamed")
            self.assertEqual(renamed.renamed_from, "abc123-Notes")
            note.assert_called_once_with("Renamed abc123-Notes -> abc123-Renamed")

    def test_rename_collision_keeps_the_existing_repository(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            first = create_repo(project(), output)
            collision = output / "abc123-Renamed"
            collision.mkdir()
            marker = collision / "keep.txt"
            marker.write_text("mine\n")

            with patch("overleaf_to_git.git_operations.STATUS.note") as note:
                result = create_repo(project("Renamed"), output)

            self.assertEqual(result.path, first.path)
            self.assertEqual(marker.read_text(), "mine\n")
            note.assert_called_once_with(
                "Not renaming abc123-Notes -> abc123-Renamed: the target already exists"
            )

    def test_local_commit_is_parked_before_the_archive_is_rebuilt(self):
        with TemporaryDirectory() as directory:
            first = create_repo(project(), directory)
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

            result = create_repo(project(), directory)
            repo = pygit2.Repository(str(first.path))

            self.assertEqual(repo.head.target, imported_tip)
            self.assertIsNotNone(result.parked)
            self.assertEqual(repo.branches[result.parked].target, local_tip)
