# -*- coding: utf-8 -*-
# pylint: disable=C0330

from __future__ import absolute_import
from textwrap import shorten
from typing import Any, Dict, List, NamedTuple

from robobrowser import RoboBrowser

from .overleaf_browser import (
    get_single_diff_v1,
    get_single_diff_v2,
    get_project_updates,
    OverleafProject,
)


class OverleafSingleRevision(NamedTuple):
    file_id: str
    before_rev: int
    after_rev: int
    contents: str
    operation: str


class OverleafRevision(NamedTuple):
    authors: List[Dict[str, str]]
    before_ts: int
    after_ts: int
    file_revs: List[OverleafSingleRevision]


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


def create_projects(
    browser: RoboBrowser, projects: List[Dict[str, Any]], indices: List[int],
) -> List[OverleafProject]:
    fmt = "[{:>36}]  {:>4}/{:>4} revision list"
    total_projs = len(indices)
    chosen_projects = []

    for list_ind, index in enumerate(indices):
        _id, name = projects[index - 1]["id"], projects[index - 1]["name"]
        msg = fmt.format(shorten(name, width=32), list_ind + 1, total_projs)
        print(msg, end="\r")

        chosen_projects.append(
            OverleafProject(_id, name, get_project_updates(browser, _id))
        )

    return chosen_projects


def create_project_history(
    browser: RoboBrowser, project: OverleafProject
) -> List[OverleafRevision]:
    fmt = "[{:>36}]  {:>4}/{:>4} individual revisions"
    changes = len(project.updates)
    all_revs = []

    for index, update in enumerate(reversed(project.updates)):
        msg = fmt.format(shorten(project.name, width=32), index + 1, changes)
        print(msg, end="\r")

        if "pathnames" not in update.keys():
            all_revs.append(create_single_rev_v1(browser, project.uid, update))
        else:
            all_revs.append(create_single_rev_v2(browser, project.uid, update))

    return all_revs


def flatten_diff(changes: Dict[str, str]) -> str:
    contents = ""
    for mod in changes:
        if mod == "binary":
            continue
        if "u" in mod.keys():
            contents += mod["u"]
        if "i" in mod.keys():
            contents += mod["i"]
    return contents


def create_single_rev_v1(
    browser: RoboBrowser, project_id: str, update: Dict[str, Any]
) -> OverleafRevision:
    revs = []

    for file_id, ver in update["docs"].items():
        sdiff = get_single_diff_v1(
            browser, project_id, file_id, ver["fromV"], ver["toV"]
        )

        revs.append(
            OverleafSingleRevision(
                file_id=file_id,
                before_rev=ver["fromV"],
                after_rev=ver["toV"],
                contents=flatten_diff(sdiff["diff"]),
                operation="sharelatex",
            )
        )

    return OverleafRevision(
        authors=update["meta"]["users"],
        before_ts=update["meta"]["start_ts"],
        after_ts=update["meta"]["end_ts"],
        file_revs=revs,
    )


def create_single_rev_v2(
    browser: RoboBrowser, project_id: str, update: Dict[str, Any]
) -> OverleafRevision:
    revs = []

    for path in update["pathnames"]:
        sdiff = get_single_diff_v2(
            browser, project_id, path, update["fromV"], update["toV"]
        )

        revs.append(
            OverleafSingleRevision(
                file_id=path,
                before_rev=update["fromV"],
                after_rev=update["toV"],
                contents=flatten_diff(sdiff["diff"]),
                operation="keep",
            )
        )

    for operation in reversed(update["project_ops"]):
        contents = ""
        _op = list(operation.keys())[0]
        path = operation[_op]["pathname"]

        if _op == "add":
            sdiff = get_single_diff_v2(
                browser, project_id, path, update["fromV"], update["toV"]
            )
            contents = flatten_diff(sdiff["diff"])

        elif _op == "rename":
            contents = operation[_op]["newPathname"]

        revs.append(
            OverleafSingleRevision(
                file_id=path,
                before_rev=update["fromV"],
                after_rev=operation["atV"],
                contents=contents,
                operation=_op,
            )
        )

    return OverleafRevision(
        authors=update["meta"]["users"],
        before_ts=update["meta"]["start_ts"],
        after_ts=update["meta"]["end_ts"],
        file_revs=revs,
    )
