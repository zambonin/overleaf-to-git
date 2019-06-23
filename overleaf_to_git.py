#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0330, W0632

from __future__ import absolute_import, division

from collections import namedtuple
from datetime import datetime
from os import chdir, environ, remove
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
    upd_meta_info: Dict[str, Union[List[Dict[str, str]], int, int]],
    files: List[str],
    _from: str,
    _to: str,
) -> CommitHeader:
    def parse_author(upd_first_user: Dict[str, str]) -> str:
        return "{} {} <{}>".format(
            upd_first_user["first_name"],
            upd_first_user["last_name"],
            upd_first_user["email"],
        )

    def parse_date(timestamp: int) -> str:
        return (
            datetime.fromtimestamp(timestamp / 1000)
            .astimezone()
            .strftime("%c %z")
        )

    def parse_message(
        upd_users: List[Dict[str, str]],
        _files: List[str],
        _from: str,
        _to: str,
    ) -> str:
        _path = _files[0] if len(_files) == 1 else "multiple files"
        message = "overleaf: update {} from r{} to r{}".format(
            _path, _from, _to
        )

        if _files[1:]:
            message += "\n* "
            message += ", ".join(files)

        if upd_users[1:]:
            message += "\n"
            message += "".join(
                "\nCo-authored-by: {}".format(parse_author(coauthor))
                for coauthor in upd_users[1:]
            )

        return message + "\n"

    return CommitHeader(
        author=parse_author(upd_meta_info["users"][0]),
        author_date=parse_date(upd_meta_info["start_ts"]),
        commit_date=parse_date(upd_meta_info["end_ts"]),
        message=parse_message(upd_meta_info["users"], files, _from, _to),
    )


def create_cur_dir_contents_v1(
    project_id: str,
    headers: Dict[str, str],
    upd: Dict[str, str],
) -> Dict[str, str]:

    return {
        file_id: get_diff_dict_v1(
            project_id, headers, file_id, rev["fromV"], rev["toV"]
        )
        for file_id, rev in upd["docs"].items()
    }


def create_cur_dir_contents_v2(
    project_id: str, headers: Dict[str, str], upd: Dict[str, str]
) -> Dict[str, str]:
    cur_dir_contents = {}

    for _file in upd["pathnames"]:
        cur_dir_contents[_file] = get_diff_dict_v2(
            project_id, headers, _file, upd["fromV"], upd["toV"]
        )

    for operation in reversed(upd["project_ops"]):
        if "add" in operation.keys():
            _path = operation["add"]["pathname"]
            cur_dir_contents[_path] = get_diff_dict_v2(
                project_id, headers, _path, upd["fromV"], upd["toV"]
            )
        elif "rename" in operation.keys():
            old_path = operation["rename"]["pathname"]
            if old_path in cur_dir_contents.keys():
                cur_dir_contents[
                    operation["rename"]["newPathname"]
                ] = cur_dir_contents[operation["rename"]["pathname"]]
                cur_dir_contents[operation["rename"]["pathname"]] = None
        elif "remove" in operation.keys():
            cur_dir_contents[operation["remove"]["pathname"]] = None

    return cur_dir_contents


def create_cur_dir_contents(
    project_id: str, headers: Dict[str, str], upd: Dict[str, str]
) -> Dict[str, str]:
    return (
        create_cur_dir_contents_v2(project_id, headers, upd)
        if "pathnames" in upd.keys()
        else create_cur_dir_contents_v1(project_id, headers, upd)
    )


def create_commit_v1(
    cur_dir_contents: Dict[str, str],
    upd: Dict[str, str],
    real_file_names: Dict[str, str],
):
    hint_length = 40
    for _path, diff in cur_dir_contents.items():
        if diff is None:
            continue
        if _path not in real_file_names.keys():
            print("\nHint: {}".format(diff[:hint_length]))
            real_file_names[_path] = input(
                "Real name of document {}: ".format(_path)
            )
        real_path = real_file_names[_path]
        commit_header = make_commit_header(
            upd["meta"],
            [real_path],
            upd["docs"][_path]["fromV"],
            upd["docs"][_path]["toV"],
        )
        commit_line = (
            "git",
            "commit",
            "--date={}".format(commit_header.author_date),
            "--author={}".format(commit_header.author),
            "--message={}".format(commit_header.message),
        )

        Path(dirname(real_path)).mkdir(parents=True, exist_ok=True)
        with open(real_path, "w") as file_handler:
            file_handler.write(diff)

        Popen("git add .".split(), stdout=PIPE).communicate()
        env = environ.copy()
        env["GIT_COMMITTER_DATE"] = commit_header.commit_date
        Popen(commit_line, stdout=PIPE, env=env).communicate()


def create_commit_v2(cur_dir_contents: Dict[str, str], upd: Dict[str, str]):
    removed_files = (
        _path for _path, diff in cur_dir_contents.items() if diff is None
    )
    for _path in removed_files:
        try:
            remove(_path)
        except FileNotFoundError:
            pass

    touched_files = [_path for _path, diff in cur_dir_contents.items() if diff]

    commit_header = make_commit_header(
        upd["meta"], touched_files, upd["fromV"], upd["toV"]
    )
    commit_line = (
        "git",
        "commit",
        "--date={}".format(commit_header.author_date),
        "--author={}".format(commit_header.author),
        "--message={}".format(commit_header.message),
    )

    for _path in touched_files:
        Path(dirname(_path)).mkdir(parents=True, exist_ok=True)
        with open(_path, "w") as file_handler:
            file_handler.write(cur_dir_contents[_path])

    Popen("git add .".split(), stdout=PIPE).communicate()
    env = environ.copy()
    env["GIT_COMMITTER_DATE"] = commit_header.commit_date
    Popen(commit_line, stdout=PIPE, env=env).communicate()


def create_commit(
    cur_dir_contents: Dict[str, str],
    upd: Dict[str, str],
    real_file_names: Dict[str, str],
):
    if "pathnames" in upd.keys():
        create_commit_v2(cur_dir_contents, upd)
    else:
        create_commit_v1(cur_dir_contents, upd, real_file_names)


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
        cur_dir_contents = create_cur_dir_contents(project_id, headers, upd)
        create_commit(cur_dir_contents, upd, real_file_names)

        percent = (index + 1) / num_commits
        bars = int(percent * bar_width) * "█"
        print("{:>7.2%} [{:<70}]".format(percent, bars), end="\r")

    print(
        "{} revisions parsed.".format(num_commits), end=" " * bar_width + "\n"
    )


if __name__ == "__main__":
    main()
