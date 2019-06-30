#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0330, W0632

from __future__ import absolute_import, division

from collections import namedtuple
from datetime import datetime
from getpass import getpass
from json import loads
from json.decoder import JSONDecodeError
from operator import itemgetter
from os import chdir, environ, remove, rename
from os.path import dirname, exists
from pathlib import Path
from subprocess import Popen, PIPE
from typing import Dict, List, Tuple, Union

from robobrowser import RoboBrowser

CommitHeader = namedtuple(
    "CommitHeader", ["author", "author_date", "commit_date", "message"]
)


def get_update_dict(
    browser, project_id: str, count: int = 1 << 20
) -> Dict[str, str]:
    browser.open(
        "https://www.overleaf.com/project/{}/updates".format(project_id),
        params={"min_count": count},
    )
    return loads(browser.parsed.text)


def get_diff_dict_v2(
    project_id: str, browser, _file: str, _from: str, _to: str
) -> Union[None, str]:
    diff_url = "https://www.overleaf.com/project/{}/diff".format(project_id)
    try:
        # if there are multiple add/remove operations within a single
        # diff range, Overleaf shows an older version of the file,
        # and due to this fact `toV` is used twice to guarantee that
        # the latest version is obtained (but it may fail anyway)
        browser.open(
            diff_url, params={"pathname": _file, "from": _to, "to": _to}
        )
        diff = loads(browser.parsed.text)
    except JSONDecodeError:
        browser.open(
            diff_url, params={"pathname": _file, "from": _from, "to": _to}
        )
        diff = loads(browser.parsed.text)

    content = ""
    for mod in diff["diff"]:
        if mod == "binary":
            content = None
            continue
        if "u" in mod.keys():
            content += mod["u"]
        if "i" in mod.keys():
            content += mod["i"]

    return content


def get_diff_dict_v1(
    project_id: str, browser, file_id: str, _from: str, _to: str
) -> Union[None, str]:
    diff_url = "https://www.overleaf.com/project/{}/doc/{}/diff".format(
        project_id, file_id
    )
    try:
        # may generate 500 error due to deleted file
        browser.open(diff_url, params={"from": _from, "to": _to})
        diff = loads(browser.parsed.text)
    except JSONDecodeError:
        return None

    content = ""
    for mod in diff["diff"]:
        if "u" in mod.keys():
            content += mod["u"]
        if "i" in mod.keys():
            content += mod["i"]

    return content


def make_commit_header(
    upd_meta_info: Dict, _from: str, _to: str, files: List[str]
) -> CommitHeader:
    def parse_author(first_author: Dict[str, str]) -> str:
        return "{} {} <{}>".format(
            first_author["first_name"],
            first_author.get("last_name", ""),
            first_author["email"],
        )

    def parse_date(timestamp: int) -> str:
        return (
            datetime.fromtimestamp(timestamp / 1000)
            .astimezone()
            .strftime("%c %z")
        )

    def parse_message(
        authors: List[Dict[str, str]], _files: List[str], _from: str, _to: str
    ) -> str:
        _path = _files[0] if len(_files) == 1 else "multiple files"
        message = "overleaf: update {} from r{} to r{}".format(
            _path, _from, _to
        )

        if _files[1:]:
            message += "\n* "
            message += ", ".join(_files)

        if authors[1:]:
            message += "\n"
            message += "".join(
                "\nCo-authored-by: {}".format(parse_author(coauthor))
                for coauthor in authors[1:]
            )

        return message + "\n"

    users = upd_meta_info["users"]
    return CommitHeader(
        author=parse_author(users[0]),
        author_date=parse_date(upd_meta_info["start_ts"]),
        commit_date=parse_date(upd_meta_info["end_ts"]),
        message=parse_message(users, files, _from, _to),
    )


def create_commit_v1(
    browser,
    project_id: str,
    upd: Dict[str, str],
    real_file_names: Dict[str, str],
):
    hint_length = 40
    for file_id, rev in upd["docs"].items():
        diff = get_diff_dict_v1(
            project_id, browser, file_id, rev["fromV"], rev["toV"]
        )
        if diff is None:
            continue

        if file_id not in real_file_names.keys():
            print("\nHint: {}".format(diff[:hint_length]))
            real_file_names[file_id] = input(
                "Real name of document {}: ".format(file_id)
            )
        real_path = real_file_names[file_id]
        write_file(diff, real_path)

        do_commit(
            upd["meta"],
            upd["docs"][file_id]["fromV"],
            upd["docs"][file_id]["toV"],
            [real_path],
        )


def write_file(contents: str, _path: str):
    Path(dirname(_path)).mkdir(parents=True, exist_ok=True)
    with open(_path, "w") as file_handler:
        file_handler.write(contents)


def do_commit(upd_meta_info: Dict, _from: str, _to: str, files: List[str]):
    commit_header = make_commit_header(upd_meta_info, _from, _to, files)
    commit_line = (
        "git",
        "commit",
        "--date={}".format(commit_header.author_date),
        "--author={}".format(commit_header.author),
        "--message={}".format(commit_header.message),
    )

    Popen("git add .".split(), stdout=PIPE).communicate()
    env = environ.copy()
    env["GIT_COMMITTER_DATE"] = commit_header.commit_date
    Popen(commit_line, stdout=PIPE, env=env).communicate()


def create_commit_v2(browser, project_id: str, upd: Dict[str, str]):
    touched_files = []
    for _path in upd["pathnames"]:
        diff = get_diff_dict_v2(
            project_id, browser, _path, upd["fromV"], upd["toV"]
        )
        if diff:
            write_file(diff, _path)
            touched_files.append(_path)

    for operation in reversed(upd["project_ops"]):
        _path = None
        if "add" in operation.keys():
            _path = operation["add"]["pathname"]
            diff = get_diff_dict_v2(
                project_id, browser, _path, upd["fromV"], upd["toV"]
            )
            if diff:
                write_file(diff, _path)
        elif "rename" in operation.keys():
            src = operation["rename"]["pathname"]
            if exists(src):
                _path = operation["rename"]["newPathname"]
                Path(dirname(_path)).mkdir(parents=True, exist_ok=True)
                rename(operation["rename"]["pathname"], _path)
        elif "remove" in operation.keys():
            # TODO do not leave empty directories
            src = operation["remove"]["pathname"]
            if exists(src):
                _path = src
                remove(_path)
        if _path:
            touched_files.append(_path)

    do_commit(upd["meta"], upd["fromV"], upd["toV"], touched_files)


def create_commit(
    browser,
    project_id: str,
    upd: Dict[str, str],
    real_file_names: Dict[str, str],
):
    if "pathnames" in upd.keys():
        create_commit_v2(browser, project_id, upd)
    else:
        create_commit_v1(browser, project_id, upd, real_file_names)


def process_input(limit: int) -> List[int]:
    exceed = True
    while exceed:
        _str = input("Choose the project indices to be imported: ")
        sequence = create_sequences(_str)
        exceed = any(num > limit for num in sequence) or not sequence
    return sequence


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


def log(message: str):
    print(message + "...", end="\r")


def login(browser, user: str, password: str):
    browser.open("https://www.overleaf.com/login")
    form = browser.get_form(action="/login")

    form["email"].value = user
    form["password"].value = password

    log("Authenticating")
    browser.submit_form(form)

    if browser.url != "https://www.overleaf.com/project":
        # automatic redirect if successful
        raise SystemExit("Authentication failed!")


def get_project_updates(browser) -> List[Tuple[str, str, Dict[str, str]]]:
    log("Getting list of projects")
    raw_json = browser.find(id="data").text
    projects = loads(raw_json)["projects"]
    ord_proj = sorted(projects, key=itemgetter("lastUpdated"), reverse=True)

    line_fmt = "{:>3} {:<40} {:<26} {:<12}"
    print(line_fmt.format("", "Project name", "Owner", "Last updated"))

    for index, project in enumerate(ord_proj):
        print(
            line_fmt.format(
                index + 1,
                project["name"],
                project["owner"]["email"],
                project["lastUpdated"][:10],
            )
        )

    proj_indices = process_input(len(ord_proj))
    proj_updates = []

    for index in proj_indices:
        _id, name = ord_proj[index - 1]["id"], ord_proj[index - 1]["name"]
        log("[{}] Getting update history".format(_id))
        proj_updates.append(
            (_id, name, get_update_dict(browser, _id)["updates"])
        )

    return proj_updates


def create_project(browser, project, cur_upd: int, max_upd: int):
    _id, name, proj_hist = project
    upd_fmt = "[{:>36}]  {:>4}/{:>4} project  {:>4}/{:>4} total"
    changes = len(proj_hist)

    Path(name).mkdir(exist_ok=True)
    chdir(name)
    Popen("git init".split(), stdout=PIPE).communicate()

    real_file_names = {}
    for index, update in enumerate(reversed(proj_hist)):
        cur_upd += 1
        log(upd_fmt.format(name, index + 1, changes, cur_upd, max_upd))
        create_commit(browser, _id, update, real_file_names)

    chdir("..")


def main():
    browser = RoboBrowser(history=True, parser="html.parser")

    login(browser, input("Your Overleaf e-mail: "), getpass("Password: "))
    updates = get_project_updates(browser)

    hist_lengths = [len(proj_hist) for _, _, proj_hist in updates]
    max_upd = sum(hist_lengths)
    for index, project in enumerate(updates):
        create_project(browser, project, sum(hist_lengths[:index]), max_upd)


if __name__ == "__main__":
    main()
