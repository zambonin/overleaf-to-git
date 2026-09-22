from tempfile import TemporaryDirectory
from unittest import TestCase

import pygit2

from overleaf_to_git.custom_types import OverleafSingleRevision
from overleaf_to_git.git_operations import create_repo, parse_message

from .helpers import AUTHOR, project, revision


class GitHistoryTests(TestCase):
    def test_rerun_reproduces_the_same_commit(self):
        with TemporaryDirectory() as directory:
            first = create_repo(project(), directory)
            first_tip = pygit2.Repository(str(first.path)).head.target

            second = create_repo(project(), directory)
            second_tip = pygit2.Repository(str(second.path)).head.target

            self.assertEqual(first.added, 1)
            self.assertEqual(second.added, 0)
            self.assertEqual(first_tip, second_tip)

    def test_empty_history_creates_an_unborn_repository(self):
        with TemporaryDirectory() as directory:
            result = create_repo(project(updates=[]), directory)
            repo = pygit2.Repository(str(result.path))

            self.assertEqual(result.added, 0)
            self.assertTrue(repo.head_is_unborn)

    def test_add_rename_and_remove_operations_build_the_expected_trees(self):
        updates = [
            revision(
                OverleafSingleRevision("paper.tex", 0, 1, "first\n", "add"),
                before=1_700_000_000_000,
                after=1_700_000_001_000,
            ),
            revision(
                OverleafSingleRevision("paper.tex", 1, 2, "main.tex", "rename"),
                before=1_700_000_002_000,
                after=1_700_000_003_000,
            ),
            revision(
                OverleafSingleRevision("main.tex", 2, 3, "", "remove"),
                before=1_700_000_004_000,
                after=1_700_000_005_000,
            ),
        ]

        with TemporaryDirectory() as directory:
            result = create_repo(project(updates=updates), directory)
            repo = pygit2.Repository(str(result.path))
            commits = list(repo.walk(repo.head.target))
            tree_names = [[entry.name for entry in commit.tree] for commit in commits]

            self.assertEqual(result.added, 3)
            self.assertEqual(len(commits), 3)
            self.assertEqual(tree_names, [[], ["main.tex"], ["paper.tex"]])

    def test_commit_message_lists_coauthors(self):
        coauthor = {
            "first_name": "Grace",
            "last_name": "Hopper",
            "email": "grace@example.com",
        }
        changed = OverleafSingleRevision("paper.tex", 1, 2, "text", "keep")

        message = parse_message([AUTHOR, coauthor], [changed])

        self.assertIn("update paper.tex from r1 to r2", message)
        self.assertIn("Co-authored-by: Grace Hopper <grace@example.com>", message)
