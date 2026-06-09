# -*- coding: utf-8 -*-
# pylint: disable=C0209
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import mkdtemp
from textwrap import shorten

import pygit2

from .custom_types import (
    OverleafAuthor,
    OverleafProjectWithHistory,
    OverleafRevision,
)

_FILEMODE_BLOB = 0o100644


def author_identity(author: OverleafAuthor) -> tuple[str, str]:
    name = "{} {}".format(
        author.get("first_name", ""), author.get("last_name", "")
    ).strip()
    return name or "Overleaf History System", author.get("email", "overle@f")


def parse_author(author: OverleafAuthor) -> str:
    name, email = author_identity(author)
    return "{} <{}>".format(name, email)


def parse_message(authors: list[OverleafAuthor], revs) -> str:
    touched = {
        rev.file_id: "update {} from r{} to r{}\n".format(
            rev.file_id, rev.before_rev, rev.after_rev
        )
        for rev in revs
    }
    message = "overleaf_to_git: " + "".join(touched.values())
    if len(authors) > 1:
        message += "\n" + "".join(
            "\nCo-authored-by: {}".format(parse_author(coauthor))
            for coauthor in authors[1:]
        )
    return message + "\n"


def _signature(author: OverleafAuthor, stamp_ms: int) -> pygit2.Signature:
    name, email = author_identity(author)
    # Overleaf timestamps have no timezone; UTC keeps commit IDs reproducible.
    return pygit2.Signature(name, email, int(stamp_ms // 1000), 0)


def _index_remove(index: pygit2.Index, path: str) -> None:
    try:
        index.remove(path)
    except (KeyError, OSError, pygit2.GitError):
        pass


def _index_rename(index: pygit2.Index, old: str, new: str) -> None:
    try:
        entry = index[old]
    except KeyError:
        return
    index.remove(old)
    index.add(pygit2.IndexEntry(new, entry.id, entry.mode))


def do_commit(
    repo: pygit2.Repository, index: pygit2.Index, update: OverleafRevision
) -> None:
    for rev in update.file_revs:
        if rev.operation == "remove":
            _index_remove(index, rev.file_id)
        elif rev.operation == "rename":
            _index_rename(index, rev.file_id, rev.contents)
        else:
            data = (
                rev.contents.encode("utf8")
                if isinstance(rev.contents, str)
                else rev.contents
            )
            blob = repo.create_blob(data)
            index.add(pygit2.IndexEntry(rev.file_id, blob, _FILEMODE_BLOB))

    index.write()
    tree = index.write_tree()
    author = _signature(update.authors[0], update.before_ts)
    committer = _signature(update.authors[0], update.after_ts)
    message = parse_message(update.authors, update.file_revs)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    repo.create_commit("HEAD", author, committer, message, tree, parents)


def create_repo(project: OverleafProjectWithHistory) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "overleaf-git-{}-{}-".format(project.name, stamp)
    repo_path = Path(mkdtemp(prefix=name))
    repo = pygit2.init_repository(str(repo_path))
    index = repo.index

    fmt = "[{:>36}]  {:>4}/{:>4} commits"
    total_commits = len(project.updates)
    for index_i, update in enumerate(project.updates):
        msg = fmt.format(shorten(str(repo_path), width=32), index_i + 1, total_commits)
        print(msg, end="\r")
        do_commit(repo, index, update)

    if not repo.head_is_unborn:
        repo.reset(repo.head.target, pygit2.GIT_RESET_HARD)
    return repo_path
