# -*- coding: utf-8 -*-
# pylint: disable=C0330

from __future__ import absolute_import
from textwrap import shorten
from typing import Any, Dict, List, NamedTuple

from robobrowser import RoboBrowser

from .overleaf_browser import get_single_diff_v1, OverleafProject


class SharelatexRevision(NamedTuple):
    file_id: str
    before_rev: int
    after_rev: int
    contents: str
    before_ts: int
    after_ts: int
    authors: List[Dict[str, str]]


def display_projects(projects: List[Dict[str, Any]]) -> str:
    output = ""
    line_fmt = "{:>4}  {:<34}  {:<22}  {:<10}\n"
    output += line_fmt.format("", "Project name", "Owner", "Last update")

    for index, project in enumerate(projects):
        email = project["owner"]["email"]
        output += line_fmt.format(
            index + 1,
            shorten(project["name"], width=34, placeholder="..."),
            (email[:18] + "...") if len(email) > 20 else email,
            project["lastUpdated"][:10],
        )

    return output


def create_sequences(string: str) -> List[int]:
    raw_numbers = string.replace("-", " ").split()
    ranges = [seq.split("-") for seq in string.split()]

    all_numbers = all(num.isdigit() for num in raw_numbers)
    any_zero = "0" in raw_numbers
    any_long_seq = any(len(seq) > 2 for seq in ranges)
    any_incomplete_seq = any("" in seq for seq in ranges)

    if not all_numbers or any_zero or any_long_seq or any_incomplete_seq:
        return []

    sequence = set()
    for item in ranges:
        numbers = list(map(int, item))
        sequence |= set(range(min(numbers), max(numbers) + 1))

    return sorted(sequence)


def create_project_history(
    browser: RoboBrowser, project: OverleafProject, cur_upd: int, max_upd: int
) -> List[List[SharelatexRevision]]:
    upd_fmt = "[{:>36}]  {:>4}/{:>4} project  {:>4}/{:>4} total"
    changes = len(project.updates)
    all_revs = []

    for index, update in enumerate(reversed(project.updates)):
        cur_upd += 1
        print(
            upd_fmt.format(project.name, index + 1, changes, cur_upd, max_upd),
            end="\r",
        )
        all_revs.append(create_single_rev_v1(browser, project.uid, update))

    return all_revs


def create_single_rev_v1(
    browser: RoboBrowser, project_id: str, update: Dict[str, Any]
) -> List[SharelatexRevision]:
    revs = []

    for file_id, ver in update["docs"].items():
        sdiff = get_single_diff_v1(
            browser, project_id, file_id, ver["fromV"], ver["toV"]
        )

        contents = ""
        for mod in sdiff["diff"]:
            if "u" in mod.keys():
                contents += mod["u"]
            if "i" in mod.keys():
                contents += mod["i"]

        revs.append(
            SharelatexRevision(
                file_id=file_id,
                before_rev=ver["fromV"],
                after_rev=ver["toV"],
                contents=contents,
                before_ts=update["meta"]["start_ts"],
                after_ts=update["meta"]["end_ts"],
                authors=update["meta"]["users"],
            )
        )

    return revs
