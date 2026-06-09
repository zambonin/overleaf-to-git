# -*- coding: utf-8 -*-
# pylint: disable=C0209
from __future__ import annotations

from pathlib import Path
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


def _sanitize(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "-" for c in name)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-_. ") or "overleaf-project"


def _unique_path(output_dir: Path, name: str) -> Path:
    candidate, suffix = output_dir / name, 1
    while candidate.exists():
        suffix += 1
        candidate = output_dir / "{}-{}".format(name, suffix)
    return candidate


def create_repo(project: OverleafProjectWithHistory, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_path = _unique_path(output_dir, _sanitize(project.name))
    repo = pygit2.init_repository(str(repo_path))
    index = repo.index

    fmt = "[{:>32}]  {:>4}/{:>4} commits"
    total_commits = len(project.updates)
    for index_i, update in enumerate(project.updates):
        msg = fmt.format(shorten(project.name, width=32), index_i + 1, total_commits)
        print(msg, end="\r")
        do_commit(repo, index, update)

    if not repo.head_is_unborn:
        repo.reset(repo.head.target, pygit2.GIT_RESET_HARD)
    return repo_path
