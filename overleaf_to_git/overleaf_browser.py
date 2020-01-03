# -*- coding: utf-8 -*-
# pylint: disable=C0330

from __future__ import absolute_import
from json import loads
from operator import itemgetter
from typing import Any, Dict, List, NamedTuple

from robobrowser import RoboBrowser


class OverleafProject(NamedTuple):
    uid: str
    name: str
    updates: List[Dict[str, Any]]


def login(browser: RoboBrowser, username: str, password: str):
    browser.open("https://www.overleaf.com/login")
    form = browser.get_form(action="/login")

    form["email"].value = username
    form["password"].value = password

    browser.submit_form(form)
    if browser.url != "https://www.overleaf.com/project":
        # automatic redirection if login was successful
        raise SystemExit("Authentication failed!")


def get_project_list(browser: RoboBrowser) -> List[Dict[str, Any]]:
    raw_json = browser.find(id="data").text
    dict_json = loads(raw_json)["projects"]
    return sorted(dict_json, key=itemgetter("lastUpdated"), reverse=True)


def get_project_updates(
    browser: RoboBrowser,
    projects: List,
    indices: List[int],
    count: int = 1 << 20,
) -> List[OverleafProject]:
    proj_updates = []
    url = "https://www.overleaf.com/project/{}/updates"

    for index in indices:
        _id, name = projects[index - 1]["id"], projects[index - 1]["name"]
        browser.open(url.format(_id), params={"min_count": count})
        dict_json = loads(browser.parsed.text)
        proj_updates.append(OverleafProject(_id, name, dict_json["updates"]))

    return proj_updates
