from io import StringIO
from os import terminal_size
from unittest import TestCase
from unittest.mock import Mock, patch

from overleaf_to_git.progress import Progress, Status, bar


class ProgressTests(TestCase):
    def test_bar_handles_empty_partial_and_complete_totals(self):
        self.assertEqual(bar(0, 0, 4), "░░░░")
        self.assertEqual(bar(2, 4, 4), "██░░")
        self.assertEqual(bar(8, 4, 4), "████")

    def test_noninteractive_status_suppresses_transient_updates(self):
        stream = StringIO()
        status = Status(stream)

        status.update("temporary")
        status.note("persistent")

        self.assertEqual(stream.getvalue(), "persistent\n")

    def test_interactive_status_replaces_and_clears_lines(self):
        stream = StringIO()
        stream.isatty = lambda: True
        status = Status(stream)

        with patch(
            "overleaf_to_git.progress.shutil.get_terminal_size",
            return_value=terminal_size((20, 24)),
        ):
            status.render(["first"])
            status.render(["second", "third"])
            status.clear()

        self.assertIn("first", stream.getvalue())
        self.assertIn("second", stream.getvalue())
        self.assertIn("\033[2K", stream.getvalue())

    def test_progress_delegates_rendering_and_cleanup(self):
        status = Mock()
        progress = Progress(3, status)

        progress.project(2, "Notes")
        progress.step("fetching", 4, 10)
        progress.done()

        self.assertEqual(status.render.call_count, 2)
        self.assertIn("Notes", status.render.call_args_list[0].args[0][0])
        self.assertIn("4/10", status.render.call_args_list[1].args[0][2])
        status.clear.assert_called_once_with()
