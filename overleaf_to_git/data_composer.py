# -*- coding: utf-8 -*-

from __future__ import absolute_import
from textwrap import shorten

from robobrowser import RoboBrowser

from .custom_types import (
    OverleafProject,
    OverleafProjectUpdate,
    OverleafProjectWithHistory,
    OverleafRawProject,
    OverleafRevision,
    OverleafSingleRevision,
)

from .overleaf_browser import (
    get_single_diff,
    get_project_updates,
    get_zip_package,
)


def display_projects(projects: list[OverleafRawProject]) -> str:
    output = ""
    line_fmt = "{:>4}  {:<34}  {:<22}  {:<10}\n"
    output += line_fmt.format("", "Project name", "Owner", "Last update")
    total_projects = len(projects)

    for index, project in enumerate(reversed(projects)):
        if not project.get("lastUpdatedBy", 1):
            email = "[!]"
        else:
            email = project["owner"]["email"]
            email = (email[:18] + "...") if len(email) > 20 else email
        output += line_fmt.format(
            total_projects - index,
            shorten(project["name"], width=34, placeholder="..."),
            email,
            project["lastUpdated"][:10],
        )

    return output


def create_sequences(string: str) -> list[int]:
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
    browser: RoboBrowser,
    projects: list[OverleafRawProject],
    indices: list[int],
) -> list[OverleafProject]:
    fmt = "[{:>36}]  {:>4}/{:>4} revision list"
    total_projects = len(indices)
    chosen_projects = []

    for list_ind, index in enumerate(indices):
        _id, name = projects[index - 1]["id"], projects[index - 1]["name"]
        msg = fmt.format(shorten(name, width=32), list_ind + 1, total_projects)
        print(msg, end="\r")

        chosen_projects.append(
            OverleafProject(_id, name, get_project_updates(browser, _id))
        )

    return chosen_projects


def create_project_history(
    browser: RoboBrowser, project: OverleafProject
) -> OverleafProjectWithHistory:
    fmt = "[{:>36}]  {:>4}/{:>4} individual revisions"
    changes = len(project.updates)
    all_revs = []

    for index, update in enumerate(reversed(project.updates)):
        msg = fmt.format(shorten(project.name, width=32), index + 1, changes)
        print(msg, end="\r")
        all_revs.append(create_single_rev(browser, project.uid, update))

    return OverleafProjectWithHistory(project.uid, project.name, all_revs)


def create_single_text_rev(
    browser: RoboBrowser,
    project_id: str,
    update: OverleafProjectUpdate,
    path: str,
) -> OverleafSingleRevision:
    keyed_diff = get_single_diff(
        browser, project_id, path, update["fromV"], update["toV"]
    )

    flat_diff = ""
    for mod in keyed_diff["diff"]:
        if mod == "binary":
            continue
        if "u" in mod:
            flat_diff += mod["u"]
        if "i" in mod:
            flat_diff += mod["i"]

    return OverleafSingleRevision(
        file_id=path,
        before_rev=update["fromV"],
        after_rev=update["toV"],
        contents=flat_diff,
        operation="keep",
    )


def create_single_binary_rev(
    browser: RoboBrowser,
    project_id: str,
    update: OverleafProjectUpdate,
    operation: dict[str, dict[str, str] | int],
) -> OverleafSingleRevision:
    _op = list(operation.keys())[0]
    path = operation[_op]["pathname"]

    contents = ""
    if _op == "add":
        zip_at_version = get_zip_package(browser, project_id, update["toV"])
        with zip_at_version.open(path) as new_file:
            contents = new_file.read()
    elif _op == "rename":
        contents = operation[_op]["newPathname"]

    return OverleafSingleRevision(
        file_id=path,
        before_rev=operation["atV"],
        after_rev=update["toV"],
        contents=contents,
        operation=_op,
    )


def create_single_rev(
    browser: RoboBrowser, project_id: str, update: OverleafProjectUpdate
) -> OverleafRevision:
    revs = []
    if update["pathnames"]:
        for path in update["pathnames"]:
            revs.append(
                create_single_text_rev(browser, project_id, update, path)
            )
    else:
        # first normalize "rename-after-add" and "delete-after-add"
        # operations to minimize ZIP downloads
        flat_ops = {}
        for operation in reversed(update["project_ops"]):
            _op = list(operation.keys())[0]
            path = operation[_op]["pathname"]
            rev = operation["atV"]

            if _op == "add":
                flat_ops[path] = (_op, "", rev)
            elif _op == "rename":
                new_path = operation[_op]["newPathname"]
                if path not in flat_ops:
                    # NULL terminator is needed for the special case
                    # of a file being renamed to something else and
                    # the old filename is reused
                    flat_ops[path + "\0"] = (_op, new_path, rev)
                else:
                    new_op, _, _ = flat_ops.pop(path)
                    flat_ops[new_path] = (new_op, "", rev)
            elif _op == "remove":
                if path not in flat_ops:
                    flat_ops[path] = (_op, "", rev)
                else:
                    del flat_ops[path]

        for path, (_op, new_path, rev) in flat_ops.items():
            operation = {
                _op: {
                    "pathname": path.split("\0")[0],
                    "newPathname": new_path,
                },
                "atV": rev,
            }
            revs.append(
                create_single_binary_rev(
                    browser, project_id, update, operation
                )
            )

    return OverleafRevision(
        authors=update["meta"]["users"],
        before_ts=update["meta"]["start_ts"],
        after_ts=update["meta"]["end_ts"],
        file_revs=revs,
    )
