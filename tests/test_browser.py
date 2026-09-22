from html import escape
from json import dumps
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import requests

from overleaf_to_git.overleaf_browser import (
    get_dashboard,
    get_project_updates,
    parse_tags,
    require_success,
    resilient_get,
)


class DashboardTests(TestCase):
    def test_reads_projects_newest_first_and_parses_tags(self):
        projects = [
            {"id": "old", "lastUpdated": "2020-01-01"},
            {"id": "new", "lastUpdated": "2026-01-01"},
        ]
        tags = [{"_id": "tag", "name": "Starred", "project_ids": ["new"]}]
        html = (
            '<meta name="ol-prefetchedProjectsBlob" content="{}">'
            '<meta name="ol-tags" content="{}">'
        ).format(
            escape(dumps({"projects": projects}), quote=True),
            escape(dumps(tags), quote=True),
        )
        client = SimpleNamespace(
            get=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=html)
        )

        found_projects, found_tags = get_dashboard(client)

        self.assertEqual([project["id"] for project in found_projects], ["new", "old"])
        self.assertEqual(found_tags[0].name, "Starred")
        self.assertEqual(found_tags[0].project_ids, frozenset({"new"}))

    def test_ignores_missing_and_unnamed_tags(self):
        self.assertEqual(parse_tags(None), [])
        self.assertEqual(parse_tags('[{"_id": "tag"}]'), [])

    def test_history_pagination_preserves_update_order(self):
        responses = [
            SimpleNamespace(
                status_code=200,
                json=lambda: {"updates": ["new"], "nextBeforeTimestamp": 10},
            ),
            SimpleNamespace(status_code=200, json=lambda: {"updates": ["old"]}),
        ]
        client = SimpleNamespace(get=Mock(side_effect=responses))

        updates = get_project_updates(client, "project", count=50)

        self.assertEqual(updates, ["new", "old"])
        self.assertEqual(
            client.get.call_args_list,
            [
                call("/project/project/updates", params={"min_count": 50}),
                call(
                    "/project/project/updates",
                    params={"min_count": 50, "before": 10},
                ),
            ],
        )


class NetworkTests(TestCase):
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

    def test_transient_failures_back_off_before_succeeding(self):
        response = SimpleNamespace(status_code=200)
        client = SimpleNamespace(
            get=Mock(
                side_effect=[
                    requests.Timeout("one"),
                    requests.ConnectionError("two"),
                    requests.exceptions.ChunkedEncodingError("three"),
                    response,
                ]
            )
        )

        with patch("overleaf_to_git.overleaf_browser.wait_visibly") as wait:
            result = resilient_get(client, "/project")

        self.assertIs(result, response)
        self.assertEqual(client.get.call_count, 4)
        self.assertEqual([item.args[0] for item in wait.call_args_list], [30, 60, 120])

    def test_non_deferred_failure_raises_after_all_attempts(self):
        client = SimpleNamespace(get=Mock(side_effect=requests.Timeout("offline")))

        with (
            patch("overleaf_to_git.overleaf_browser.wait_visibly"),
            self.assertRaises(requests.Timeout),
        ):
            resilient_get(client, "/project", defer=False)

        self.assertEqual(client.get.call_count, 4)
