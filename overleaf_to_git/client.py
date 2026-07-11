# -*- coding: utf-8 -*-
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_BASE_URL = "https://www.overleaf.com"
DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_FACTOR = 5.0
DEFAULT_COOKIE_NAME = "overleaf_session2"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)


class _MetaContentParser(HTMLParser):
    def __init__(self, meta_name: str) -> None:
        super().__init__()
        self._wanted = meta_name
        self.content: str | None = None

    def handle_starttag(self, tag, attrs) -> None:
        if tag != "meta" or self.content is not None:
            return
        attr = dict(attrs)
        if attr.get("name") == self._wanted:
            self.content = attr.get("content")


def find_meta_content(html: str, meta_name: str) -> str | None:
    parser = _MetaContentParser(meta_name)
    parser.feed(html)
    return parser.content


def registrable_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class OverleafClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        cache_dir: str | Path,
        user_agent: str = DEFAULT_USER_AGENT,
        session: requests.Session | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._mount_retries(retries, backoff_factor)

    def _mount_retries(self, retries: int, backoff_factor: float) -> None:
        policy = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            allowed_methods={"GET", "HEAD"},
            status_forcelist=(502, 503, 504),
            backoff_factor=backoff_factor,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=policy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def set_session_cookie(self, value: str, name: str = DEFAULT_COOKIE_NAME) -> None:
        self.session.cookies.set(name, value, domain=self.host)

    def load_browser_cookies(self, browser: str = "firefox") -> None:
        try:
            import browser_cookie3
        except ImportError as exc:
            raise SystemExit(
                "--from-browser needs the optional dependency; install with "
                "`uv sync --extra browser` or `pip install browser_cookie3`."
            ) from exc
        loader = getattr(browser_cookie3, browser, None)
        if loader is None:
            raise SystemExit("unsupported browser for cookie import: " + browser)
        self.session.cookies.update(loader(domain_name=registrable_domain(self.host)))

    def authenticated(self) -> bool:
        return len(self.session.cookies) > 0

    def get(self, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.get(self.base_url + path, **kwargs)
