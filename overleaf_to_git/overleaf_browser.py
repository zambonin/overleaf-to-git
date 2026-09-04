# -*- coding: utf-8 -*-
# pylint: disable=C0209
from __future__ import annotations

from functools import wraps
from json import dumps, load, loads
from operator import itemgetter
from os import environ
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic, sleep
from zipfile import BadZipFile, ZipFile

import requests
from ratelimit import limits, RateLimitException

from .client import OverleafClient, find_meta_content
from .custom_types import (
    OverleafProjectUpdate,
    OverleafRawProject,
    OverleafRawRevision,
    OverleafTag,
)
from .progress import STATUS

NETWORK_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)
GET_ATTEMPTS = 4
GET_BACKOFF = 30
GET_COOLDOWN = 600
ZIP_TIMEOUT = 300
ZIP_PERIOD = int(environ.get("OVERLEAF_ZIP_PERIOD", 120))
ANNOUNCE_AFTER = 5.0


def get_dashboard(
    client: OverleafClient,
) -> tuple[list[OverleafRawProject], list[OverleafTag]]:
    response = resilient_get(client, "/project", defer=False)
    raw_json = find_meta_content(response.text, "ol-prefetchedProjectsBlob")
    if raw_json is None:
        raise SystemExit(
            "Could not read the project list. The session is probably not "
            "authenticated -- check --session / --from-browser and --base-url."
        )
    projects = loads(raw_json)["projects"]
    projects.sort(key=itemgetter("lastUpdated"), reverse=True)
    return projects, parse_tags(find_meta_content(response.text, "ol-tags"))


def parse_tags(raw_json: str | None) -> list[OverleafTag]:
    if not raw_json:
        return []
    return [
        OverleafTag(
            uid=tag.get("_id", ""),
            name=tag.get("name", ""),
            project_ids=frozenset(tag.get("project_ids", ())),
        )
        for tag in loads(raw_json)
        if tag.get("name")
    ]


def get_project_list(client: OverleafClient) -> list[OverleafRawProject]:
    return get_dashboard(client)[0]


def get_project_updates(
    client: OverleafClient, project_id: str, count: int = 1 << 20
) -> list[OverleafProjectUpdate]:
    path = "/project/{}/updates".format(project_id)
    history: list[OverleafProjectUpdate] = []

    response = resilient_get(client, path, defer=False, params={"min_count": count})
    if response.status_code == 403:
        raise SystemExit(
            "Overleaf denied access to history for project {} (HTTP 403)".format(
                project_id
            )
        )

    data = response.json()
    history += data["updates"]
    while "nextBeforeTimestamp" in data:
        response = resilient_get(
            client,
            path,
            defer=False,
            params={"min_count": count, "before": data["nextBeforeTimestamp"]},
        )
        data = response.json()
        history += data["updates"]

    return history


def project_cache_dir(client: OverleafClient, project_id: str) -> Path:
    cache = client.cache_dir / project_id
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _retry_after(response: requests.Response, default: int) -> int:
    try:
        return int(response.headers.get("Retry-After", default))
    except (TypeError, ValueError):
        return default


def wait_visibly(seconds: float, reason: str) -> None:
    if seconds < ANNOUNCE_AFTER:
        sleep(max(seconds, 0.0))
        return

    STATUS.note("{}; waiting {:.0f}s".format(reason, seconds))
    deadline = monotonic() + seconds
    remaining = seconds
    while remaining > 0:
        STATUS.update(
            "{}; retrying in {:.0f}s (Ctrl-C to stop)".format(reason, remaining)
        )
        sleep(min(1.0, remaining))
        remaining = deadline - monotonic()
    STATUS.clear()


def cooldown_and_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        while True:
            try:
                return func(*args, **kwargs)
            except RateLimitException as exc:
                wait_visibly(max(exc.period_remaining, 0.0), str(exc))

    return wrapper


def resilient_get(
    client: OverleafClient, url: str, defer: bool = True, **kwargs
) -> requests.Response:
    delay = GET_BACKOFF
    for attempt in range(1, GET_ATTEMPTS + 1):
        try:
            return client.get(url, **kwargs)
        except NETWORK_ERRORS as exc:
            if attempt == GET_ATTEMPTS:
                if not defer:
                    raise
                raise RateLimitException(
                    "network error: {}".format(exc), GET_COOLDOWN
                ) from exc
            wait_visibly(
                delay,
                "{}: {} (attempt {}/{})".format(url, exc, attempt, GET_ATTEMPTS),
            )
            delay *= 2
    raise AssertionError("unreachable")


def get_zip_package(client: OverleafClient, project_id: str, rev_id: int) -> ZipFile:
    full_path = project_cache_dir(client, project_id) / "{}.zip".format(rev_id)
    if not full_path.exists():
        data = get_zip_package_remote(client, project_id, rev_id)
        with NamedTemporaryFile(dir=full_path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        try:
            with ZipFile(temporary, "r") as archive:
                bad_member = archive.testzip()
                if bad_member is not None:
                    raise BadZipFile("CRC failure in " + bad_member)
            temporary.replace(full_path)
        finally:
            temporary.unlink(missing_ok=True)
    return ZipFile(full_path, "r")


@cooldown_and_retry
@limits(calls=1, period=ZIP_PERIOD)
def get_zip_package_remote(
    client: OverleafClient, project_id: str, rev_id: int
) -> bytes:
    url = "/project/{}/version/{}/zip".format(project_id, rev_id)
    response = resilient_get(client, url, timeout=ZIP_TIMEOUT)

    if response.status_code == 429:
        raise RateLimitException("HTTP 429", _retry_after(response, 300))
    data = response.content
    if data.startswith(b"Rate limit reached"):
        raise RateLimitException("ZIP rate limit reached", 300)
    return data


def get_single_diff(
    client: OverleafClient,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> OverleafRawRevision:
    cached = "{}_{}_{}.json".format(file_id.replace("/", "-"), old_rev_id, new_rev_id)
    full_path = project_cache_dir(client, project_id) / cached
    if not full_path.exists():
        data = get_single_diff_remote(
            client, project_id, file_id, old_rev_id, new_rev_id
        )
        encoded = dumps(data, ensure_ascii=False).encode("utf8")
        with NamedTemporaryFile(dir=full_path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
        try:
            with temporary.open(encoding="utf8") as handle:
                load(handle)
            temporary.replace(full_path)
        finally:
            temporary.unlink(missing_ok=True)
    with open(full_path, "r", encoding="utf8") as handle:
        return load(handle)


@cooldown_and_retry
@limits(calls=1, period=1)
def get_single_diff_remote(
    client: OverleafClient,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> OverleafRawRevision:
    url = "/project/{}/diff".format(project_id)
    response = resilient_get(
        client,
        url,
        params={"pathname": file_id, "from": old_rev_id, "to": new_rev_id},
    )
    if response.status_code == 429:
        raise RateLimitException("HTTP 429", _retry_after(response, 60))
    if response.status_code == 500:
        raise RateLimitException("diff rate limit reached", 60)
    return response.json()
