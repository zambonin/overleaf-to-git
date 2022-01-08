# -*- coding: utf-8 -*-
# pylint: disable=C0209

from __future__ import absolute_import
from glob import glob
from json import dump, load, loads
from operator import itemgetter
from os import path
from tempfile import gettempdir, mkdtemp
from zipfile import ZipFile

from robobrowser import RoboBrowser

from .custom_types import (
    OverleafProjectUpdate,
    OverleafRawProject,
    OverleafRawRevision,
)


def get_project_list(browser: RoboBrowser) -> list[OverleafRawProject]:
    browser.open("https://www.overleaf.com/project")
    raw_json = browser.find("meta", attrs={"name": "ol-projects"})["content"]
    dict_json = loads(raw_json)
    return sorted(dict_json, key=itemgetter("lastUpdated"), reverse=True)


def get_project_updates(
    browser: RoboBrowser, _id: str, count: int = 1 << 20
) -> list[OverleafProjectUpdate]:
    url = "https://www.overleaf.com/project/{}/updates"
    history = []

    browser.open(url.format(_id), params={"min_count": count})
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
    find_cache_dir = glob(path.join(gettempdir(), proj_id + "-*"))
    if not find_cache_dir:
        return mkdtemp(prefix=proj_id + "-")
    return find_cache_dir[0]


def cache_zip_responses(func):
    def decorated(*args, **kwargs) -> ZipFile:
        _, proj_id, rev_id = args

        cached_zip_path = "{}.zip".format(rev_id)
        full_path = path.join(get_or_create_temp_dir(proj_id), cached_zip_path)

        if not path.exists(full_path):
            data = func(*args, **kwargs)
            with open(full_path, "wb+") as file:
                file.write(data)

        return ZipFile(full_path, "r")

    return decorated


def cache_json_responses(func):
    def decorated(*args, **kwargs) -> dict:
        _, proj_id, file_id, old_id, new_id = args

        cached_json_path = "{}_{}_{}.json".format(
            file_id.replace("/", "-"), old_id, new_id
        )
        full_path = path.join(
            get_or_create_temp_dir(proj_id), cached_json_path
        )

        if not path.exists(full_path):
            data = func(*args, **kwargs)
            with open(full_path, "w+", encoding="utf8") as file:
                dump(data, file, ensure_ascii=False)

        return load(open(full_path, "r", encoding="utf8"))

    return decorated


@cache_zip_responses
def get_zip_package(
    browser: RoboBrowser, project_id: str, rev_id: int
) -> ZipFile | bytes:
    zip_url = "https://www.overleaf.com/project/{}/version/{}/zip".format(
        project_id, rev_id
    )
    browser.open(zip_url)
    return browser.response.content


@cache_json_responses
def get_single_diff(
    browser: RoboBrowser,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> OverleafRawRevision:
    diff_url = "https://www.overleaf.com/project/{}/diff".format(project_id)
    browser.open(
        diff_url,
        params={"pathname": file_id, "from": old_rev_id, "to": new_rev_id},
    )

    if browser.response.status_code == 500:
        return {"diff": [{}]}

    return browser.response.json()
