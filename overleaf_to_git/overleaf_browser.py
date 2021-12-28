# -*- coding: utf-8 -*-
# pylint: disable=C0209

from __future__ import absolute_import
from glob import glob
from json import dump, load, loads
from operator import itemgetter
from os import path
from tempfile import gettempdir, mkdtemp

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


def cache_responses(func):
    def decorated(*args, **kwargs):
        _, proj_id, file_id, old_id, new_id = args
        find_cache_dir = glob(path.join(gettempdir(), proj_id + "-*"))
        if not find_cache_dir:
            cache_dir = mkdtemp(prefix=proj_id + "-")
        else:
            cache_dir = find_cache_dir[0]

        cached_json_path = "{}_{}_{}.json".format(
            file_id.replace("/", "-"), old_id, new_id
        )
        full_path = path.join(cache_dir, cached_json_path)

        if not path.exists(full_path):
            data = func(*args, **kwargs)
            with open(full_path, "w+", encoding="utf8") as file:
                dump(data, file, ensure_ascii=False)

        return load(open(full_path, "r", encoding="utf8"))

    return decorated


@cache_responses
def get_single_diff_v1(
    browser: RoboBrowser,
    project_id: str,
    file_id: str,
    old_rev_id: int,
    new_rev_id: int,
) -> OverleafRawRevision:
    diff_url = "https://www.overleaf.com/project/{}/doc/{}/diff".format(
        project_id, file_id
    )
    browser.open(diff_url, params={"from": old_rev_id, "to": new_rev_id})

    if browser.response.status_code == 500:
        return {"diff": [{}]}

    return browser.response.json()


@cache_responses
def get_single_diff_v2(
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
