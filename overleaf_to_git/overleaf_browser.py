# -*- coding: utf-8 -*-
# pylint: disable=C0209
from __future__ import annotations

from json import dump, load, loads
from operator import itemgetter
from pathlib import Path
from zipfile import ZipFile

import requests
from ratelimit import limits, sleep_and_retry, RateLimitException

from .client import OverleafClient, find_meta_content
from .custom_types import (
    OverleafProjectUpdate,
    OverleafRawProject,
    OverleafRawRevision,
)


def get_project_list(client: OverleafClient) -> list[OverleafRawProject]:
    response = client.get("/project")
    raw_json = find_meta_content(response.text, "ol-prefetchedProjectsBlob")
    if raw_json is None:
        raise SystemExit(
            "Could not read the project list. The session is probably not "
            "authenticated -- check --session / --from-browser and --base-url."
        )
    projects = loads(raw_json)["projects"]
    return sorted(projects, key=itemgetter("lastUpdated"), reverse=True)


def get_project_updates(
    client: OverleafClient, project_id: str, count: int = 1 << 20
) -> list[OverleafProjectUpdate]:
    path = "/project/{}/updates".format(project_id)
    history: list[OverleafProjectUpdate] = []

    response = client.get(path, params={"min_count": count})
    if response.status_code == 403:
        return history

    data = response.json()
    history += data["updates"]
    while "nextBeforeTimestamp" in data:
        response = client.get(
            path,
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


def get_zip_package(client: OverleafClient, project_id: str, rev_id: int) -> ZipFile:
    full_path = project_cache_dir(client, project_id) / "{}.zip".format(rev_id)
    if not full_path.exists():
        full_path.write_bytes(get_zip_package_remote(client, project_id, rev_id))
    return ZipFile(full_path, "r")


@sleep_and_retry
@limits(calls=1, period=60)
def get_zip_package_remote(
    client: OverleafClient, project_id: str, rev_id: int
) -> bytes:
    url = "/project/{}/version/{}/zip".format(project_id, rev_id)
    try:
        response = client.get(url)
    except requests.exceptions.ConnectionError as exc:
        raise RateLimitException("connection aborted", 600) from exc

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
        with open(full_path, "w", encoding="utf8") as handle:
            dump(data, handle, ensure_ascii=False)
    with open(full_path, "r", encoding="utf8") as handle:
        return load(handle)


@sleep_and_retry
@limits(calls=1, period=1)
def get_single_diff_remote(
    client: OverleafClient,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> OverleafRawRevision:
    url = "/project/{}/diff".format(project_id)
    response = client.get(
        url, params={"pathname": file_id, "from": old_rev_id, "to": new_rev_id}
    )
    if response.status_code == 429:
        raise RateLimitException("HTTP 429", _retry_after(response, 60))
    if response.status_code == 500:
        raise RateLimitException("diff rate limit reached", 60)
    return response.json()
