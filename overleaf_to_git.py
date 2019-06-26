#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0330, W0632

from __future__ import absolute_import, division

from collections import namedtuple
from datetime import datetime
from os import chdir, environ, remove, rename
from os.path import dirname
from json.decoder import JSONDecodeError
from pathlib import Path
from subprocess import Popen, PIPE
from sys import argv
from typing import Dict, List, Union

from requests import get as rget

CommitHeader = namedtuple(
    "CommitHeader", ["author", "author_date", "commit_date", "message"]
)


def get_update_dict(
    project_id: str, headers: Dict[str, str], count: int = 1 << 20
) -> Dict[str, str]:
    return rget(
        "https://www.overleaf.com/project/{}/updates".format(project_id),
        params={"min_count": count},
        headers=headers,
    ).json()


def get_diff_dict_v2(
    project_id: str, headers: Dict[str, str], _file: str, _from: str, _to: str
) -> Union[None, str]:
    diff_url = "https://www.overleaf.com/project/{}/diff".format(project_id)

    try:
        # if there are multiple add/remove operations within a single
        # diff range, Overleaf shows an older version of the file,
        # and due to this fact `toV` is used twice to guarantee that
        # the latest version is obtained (but it may fail anyway)
        diff = rget(
            diff_url,
            params={"pathname": _file, "from": _to, "to": _to},
            headers=headers,
        ).json()
    except JSONDecodeError:
        diff = rget(
            diff_url,
            params={"pathname": _file, "from": _from, "to": _to},
            headers=headers,
        ).json()

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
    project_id: str,
    headers: Dict[str, str],
    file_id: str,
    _from: str,
    _to: str,
) -> Union[None, str]:
    diff_url = "https://www.overleaf.com/project/{}/doc/{}/diff".format(
        project_id, file_id
    )
    try:
        # 500 error due to deleted file
        diff = rget(
            diff_url, params={"from": _from, "to": _to}, headers=headers
        ).json()
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
    project_id: str,
    headers: Dict[str, str],
    upd: Dict[str, str],
    real_file_names: Dict[str, str],
):
    hint_length = 40
    for file_id, rev in upd["docs"].items():
        diff = get_diff_dict_v1(
            project_id, headers, file_id, rev["fromV"], rev["toV"]
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


def write_file(contents: Union[None, str], _path: str):
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


def create_commit_v2(
    project_id: str, headers: Dict[str, str], upd: Dict[str, str]
):
    touched_files = []
    for _path in upd["pathnames"]:
        diff = get_diff_dict_v2(
            project_id, headers, _path, upd["fromV"], upd["toV"]
        )
        write_file(diff, _path)
        touched_files.append(_path)

    for operation in reversed(upd["project_ops"]):
        _path = None
        if "add" in operation.keys():
            _path = operation["add"]["pathname"]
            diff = get_diff_dict_v2(
                project_id, headers, _path, upd["fromV"], upd["toV"]
            )
            write_file(diff, _path)
        elif "rename" in operation.keys():
            _path = operation["rename"]["newPathname"]
            rename(operation["rename"]["pathname"], _path)
        elif "remove" in operation.keys():
            _path = operation["remove"]["pathname"]
            remove(_path)
        touched_files.append(_path)

    do_commit(upd["meta"], upd["fromV"], upd["toV"], touched_files)


def create_commit(
    project_id: str,
    headers: Dict[str, str],
    upd: Dict[str, str],
    real_file_names: Dict[str, str],
):
    if "pathnames" in upd.keys():
        create_commit_v2(project_id, headers, upd)
    else:
        create_commit_v1(project_id, headers, upd, real_file_names)


def main():
    assert len(argv) == 3, "Please input parameters correctly."
    _, project_id, req_head_path = argv

    with open(req_head_path, "r") as head:
        data = [header.strip("\n").split(": ") for header in head.readlines()]
        headers = {field.lower(): content for field, content in data}

    print("Getting list of updates...", end="\r")
    updates = get_update_dict(project_id, headers)["updates"]

    Path(project_id).mkdir(exist_ok=True)
    chdir(project_id)
    Popen("git init".split(), stdout=PIPE).communicate()

    num_commits, bar_width = len(updates), 70
    real_file_names = {}
    for index, upd in enumerate(reversed(updates)):
        create_commit(project_id, headers, upd, real_file_names)
        percent = (index + 1) / num_commits
        bars = int(percent * bar_width) * "█"
        print("{:>7.2%} [{:<70}]".format(percent, bars), end="\r")

    print(
        "{} revisions parsed.".format(num_commits), end=" " * bar_width + "\n"
    )


if __name__ == "__main__":
    main()
