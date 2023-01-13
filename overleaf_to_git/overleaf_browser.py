# -*- coding: utf-8 -*-
# pylint: disable=C0209

from __future__ import absolute_import
from glob import glob
from json import dump, load, loads
from operator import itemgetter
from os import path
from tempfile import gettempdir, mkdtemp
from zipfile import ZipFile

from ratelimit import limits, sleep_and_retry, RateLimitException
from robobrowser import RoboBrowser

from .custom_types import (
    OverleafProjectUpdate,
    OverleafRawProject,
    OverleafRawRevision,
)


def get_project_list(browser: RoboBrowser) -> list[OverleafRawProject]:
    projects_url = "https://www.overleaf.com/project"
    tag_content = "ol-prefetchedProjectsBlob"
    browser.open(projects_url)
    raw_json = browser.find("meta", attrs={"name": tag_content})["content"]
    dict_json = loads(raw_json)["projects"]
    return sorted(dict_json, key=itemgetter("lastUpdated"), reverse=True)


def get_project_updates(
    browser: RoboBrowser, _id: str, count: int = 1 << 20
) -> list[OverleafProjectUpdate]:
    url = "https://www.overleaf.com/project/{}/updates"
    history = []

    browser.open(url.format(_id), params={"min_count": count})
    if browser.response.status_code == 403:
        # forbidden to access update history
        return history

    data = browser.response.json()
    history += data["updates"]

    while "nextBeforeTimestamp" in data.keys():
        browser.open(
            url.format(_id),
            params={"min_count": count, "before": data["nextBeforeTimestamp"]},
        )
        data = browser.response.json()
        history += data["updates"]

    return history


def get_or_create_temp_dir(proj_id: str) -> str:
    name = "overleaf-updates-{}-".format(proj_id)
    find_cache_dir = glob(path.join(gettempdir(), name + "*"))
    if not find_cache_dir:
        return mkdtemp(prefix=name)
    return find_cache_dir[0]


def get_zip_package(
    browser: RoboBrowser, project_id: str, rev_id: int
) -> ZipFile:
    cached_zip_path = "{}.zip".format(rev_id)
    full_path = path.join(get_or_create_temp_dir(project_id), cached_zip_path)

    if not path.exists(full_path):
        data = get_zip_package_remote(browser, project_id, rev_id)
        with open(full_path, "wb+") as file:
            file.write(data)

    return ZipFile(full_path, "r")


@sleep_and_retry
@limits(calls=1, period=30)
def get_zip_package_remote(
    browser: RoboBrowser, project_id: str, rev_id: int
) -> bytes:
    zip_url = "https://www.overleaf.com/project/{}/version/{}/zip".format(
        project_id, rev_id
    )
    browser.open(zip_url)

    data = browser.response.content
    if data.startswith(b"Rate limit reached"):
        # stop for 10 minutes
        raise RateLimitException("ZIP call rate limit reached", 600)

    return data


def get_single_diff(
    browser: RoboBrowser,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> OverleafRawRevision:
    cached_json_path = "{}_{}_{}.json".format(
        file_id.replace("/", "-"), old_rev_id, new_rev_id
    )
    full_path = path.join(get_or_create_temp_dir(project_id), cached_json_path)

    if not path.exists(full_path):
        data = get_single_diff_remote(
            browser, project_id, file_id, old_rev_id, new_rev_id
        )
        with open(full_path, "w+", encoding="utf8") as file:
            dump(data, file, ensure_ascii=False)

    return load(open(full_path, "r", encoding="utf8"))


@sleep_and_retry
@limits(calls=1, period=1)
def get_single_diff_remote(
    browser: RoboBrowser,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> bytes:
    diff_url = "https://www.overleaf.com/project/{}/diff".format(project_id)
    browser.open(
        diff_url,
        params={"pathname": file_id, "from": old_rev_id, "to": new_rev_id},
    )

    if browser.response.status_code == 500:
        # stop for 10 minutes
        raise RateLimitException("JSON call rate limit reached", 600)

    return browser.response.json()
