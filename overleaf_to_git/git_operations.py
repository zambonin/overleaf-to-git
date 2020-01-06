# -*- coding: utf-8 -*-
# pylint: disable=C0330,W1639

from __future__ import absolute_import, division
from datetime import datetime
from os import chdir, environ, path
from pathlib import Path
from subprocess import Popen, PIPE
from tempfile import mkdtemp
from textwrap import shorten
from typing import Dict, List

from .data_composer import (
    OverleafProjectWithHistory,
    OverleafSingleRevision,
    OverleafRevision,
)


def parse_author(first_author: Dict[str, str]) -> str:
    if "last_name" in first_author.keys() and first_author["last_name"]:
        return "{} {} <{}>".format(
            first_author["first_name"],
            first_author["last_name"],
            first_author["email"],
        )
    return "{} <{}>".format(first_author["first_name"], first_author["email"])


def parse_date(stamp: int) -> str:
    return datetime.fromtimestamp(stamp / 1000).astimezone().strftime("%c %z")


def parse_message(
    authors: Dict[str, str], revs: List[OverleafSingleRevision]
) -> str:
    message = "overleaf_to_git: "
    touched = {}
    for rev in revs:
        touched[rev.file_id] = "update {} from r{} to r{}\n".format(
            rev.file_id, rev.before_rev, rev.after_rev
        )

    for line in touched:
        message += touched[line]

    if len(authors) > 1:
        message += "\n"
        message += "".join(
            "\nCo-authored-by: {}".format(parse_author(coauthor))
            for coauthor in authors[1:]
        )

    return message + "\n"


def file_inside_dir(file_path: str):
    head, _ = path.split(file_path)
    if head:
        Path(head).mkdir(parents=True, exist_ok=True)


def write_file(file_path: str, contents: str):
    file_inside_dir(file_path)
    with open(file_path, "w+", encoding="utf8") as file_handler:
        file_handler.write(contents)


def do_commit(update: OverleafRevision):
    for rev in update.file_revs:
        if rev.operation == "remove":
            command = ["git", "rm", "-f", rev.file_id]
        elif rev.operation == "rename":
            file_inside_dir(rev.contents)
            command = ["git", "mv", rev.file_id, rev.contents]
        else:
            write_file(rev.file_id, rev.contents)
            command = ["git", "add", "-f", rev.file_id]
        Popen(command, stdout=PIPE).communicate()

    commit_line = (
        "git",
        "commit",
        "--date={}".format(parse_date(update.before_ts)),
        "--author={}".format(parse_author(update.authors[0])),
        "--message={}".format(parse_message(update.authors, update.file_revs)),
    )

    env = environ.copy()
    env["GIT_COMMITTER_DATE"] = parse_date(update.after_ts)
    Popen(commit_line, stdout=PIPE, env=env).communicate()


def create_repo(project: OverleafProjectWithHistory):
    repo_path = mkdtemp(prefix="git-{}-".format(project.name))
    chdir(repo_path)
    Popen("git init".split(), stdout=PIPE).communicate()

    fmt = "[{:>36}]  {:>4}/{:>4} commits"
    total_commits = len(project.updates)

    for ind, update in enumerate(project.updates):
        msg = fmt.format(shorten(repo_path, width=32), ind + 1, total_commits)
        print(msg, end="\r")
        do_commit(update)
