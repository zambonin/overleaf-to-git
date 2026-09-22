from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

import requests

from overleaf_to_git.client import (
    OverleafClient,
    find_meta_content,
    registrable_domain,
)


class ClientTests(TestCase):
    def test_finds_and_decodes_the_first_matching_meta_value(self):
        html = (
            '<meta name="token" content="one&amp;two">'
            '<meta name="token" content="ignored">'
        )

        self.assertEqual(find_meta_content(html, "token"), "one&two")
        self.assertIsNone(find_meta_content(html, "missing"))

    def test_configures_retries_for_both_http_schemes(self):
        with TemporaryDirectory() as directory:
            session = requests.Session()
            OverleafClient(
                cache_dir=directory,
                session=session,
                retries=3,
                backoff_factor=2.5,
            )

        for scheme in ("http://", "https://"):
            retry = session.adapters[scheme].max_retries
            self.assertEqual(retry.total, 3)
            self.assertEqual(retry.backoff_factor, 2.5)
            self.assertEqual(retry.status_forcelist, (502, 503, 504))

    def test_get_builds_the_url_and_applies_the_default_timeout(self):
        with TemporaryDirectory() as directory:
            session = requests.Session()
            session.get = Mock(return_value="response")
            client = OverleafClient(
                "https://overleaf.example/",
                cache_dir=directory,
                session=session,
                timeout=17,
            )

            response = client.get("/project", params={"page": 2})

        self.assertEqual(response, "response")
        session.get.assert_called_once_with(
            "https://overleaf.example/project", params={"page": 2}, timeout=17
        )

    def test_sets_a_session_cookie_for_the_instance_host(self):
        with TemporaryDirectory() as directory:
            client = OverleafClient(
                "https://sharelatex.example.edu", cache_dir=Path(directory)
            )

            client.set_session_cookie("secret", "sharelatex.sid")

        self.assertEqual(
            client.session.cookies.get_dict(domain="sharelatex.example.edu"),
            {"sharelatex.sid": "secret"},
        )

    def test_uses_a_best_effort_registrable_domain_for_browser_cookies(self):
        self.assertEqual(registrable_domain("www.overleaf.com"), "overleaf.com")
        self.assertEqual(registrable_domain("localhost"), "localhost")
