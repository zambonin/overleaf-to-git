# -*- coding: utf-8 -*-
# pylint: disable=C0209
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pygit2

from .custom_types import (
    ArchiveResult,
    OverleafAuthor,
    OverleafProjectWithHistory,
    OverleafRevision,
)
from .progress import STATUS, Progress

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
    repo: pygit2.Repository,
    index: pygit2.Index,
    update: OverleafRevision,
    parent: pygit2.Oid | None,
) -> pygit2.Oid:
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

    tree = index.write_tree(repo)
    author = _signature(update.authors[0], update.before_ts)
    committer = _signature(update.authors[0], update.after_ts)
    message = parse_message(update.authors, update.file_revs)
    parents = [] if parent is None else [parent]
    return repo.create_commit(None, author, committer, message, tree, parents)


def find_existing_repo(output_dir: Path, project_id: str) -> Path | None:
    for pattern in ("{}-*", "*/{}-*"):
        for path in sorted(output_dir.glob(pattern.format(project_id))):
            if (path / ".git").exists():
                return path
    return None


def preserve_local_work(repo: pygit2.Repository, tip: pygit2.Oid) -> str | None:
    if repo.head_is_unborn:
        return None
    head = repo.head.target
    if head == tip or repo.descendant_of(tip, head):
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name, suffix = "local/{}".format(stamp), 1
    while name in repo.branches.local:
        suffix += 1
        name = "local/{}-{}".format(stamp, suffix)
    repo.branches.local.create(name, repo.head.peel(pygit2.Commit))
    return name


def prune_subsumed(repo: pygit2.Repository, tip: pygit2.Oid) -> int:
    pruned = 0
    for name in [b for b in repo.branches.local if b.startswith("local/")]:
        branch = repo.branches.local[name]
        if branch.target == tip or repo.descendant_of(tip, branch.target):
            branch.delete()
            pruned += 1
    return pruned


def _branch_ref(repo: pygit2.Repository) -> str:
    if repo.head_is_unborn:
        return repo.references["HEAD"].target
    return repo.head.name


def _sanitize(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "-" for c in name)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-_. ") or "overleaf-project"


def _target_path(
    project: OverleafProjectWithHistory, output_dir: Path, group_by_tag: bool
) -> Path:
    if group_by_tag and project.tags:
        output_dir /= _sanitize(project.tags[0])
    return output_dir / "{}-{}".format(project.uid, _sanitize(project.name))


def _relocate(existing: Path, target: Path) -> Path:
    if existing == target:
        return existing
    if target.exists():
        STATUS.note(
            "Not renaming {} -> {}: the target already exists".format(
                existing.name, target.name
            )
        )
        return existing
    target.parent.mkdir(parents=True, exist_ok=True)
    existing.rename(target)
    STATUS.note("Renamed {} -> {}".format(existing.name, target.name))
    return target


def _count_new(
    repo: pygit2.Repository, tip: pygit2.Oid, head: pygit2.Oid | None
) -> int:
    walker = repo.walk(tip)
    if head is not None and head in repo:
        walker.hide(head)
    return sum(1 for _ in walker)


def create_repo(
    project: OverleafProjectWithHistory,
    output_dir: Path,
    group_by_tag: bool = False,
    progress: Progress | None = None,
) -> ArchiveResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = _target_path(project, output_dir, group_by_tag)

    renamed_from = None
    existing = find_existing_repo(output_dir, project.uid)
    if existing is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        repo_path = target
        repo = pygit2.init_repository(str(repo_path))
    else:
        repo = pygit2.Repository(str(existing))
        if repo.status():
            raise SystemExit(
                "Refusing to archive into a repository with uncommitted "
                "changes: " + str(existing)
            )
        repo_path = _relocate(existing, target)
        if repo_path != existing:
            renamed_from = existing.name
        repo = pygit2.Repository(str(repo_path))

    head = None if repo.head_is_unborn else repo.head.target

    index = pygit2.Index()
    tip: pygit2.Oid | None = None
    total_commits = len(project.updates)
    for index_i, update in enumerate(project.updates):
        if progress:
            progress.step("building", index_i + 1, total_commits)
        tip = do_commit(repo, index, update, tip)

    if tip is None:
        return ArchiveResult(repo_path, renamed_from=renamed_from)

    parked = preserve_local_work(repo, tip)
    prune_subsumed(repo, tip)
    added = _count_new(repo, tip, head)
    branch = _branch_ref(repo)
    repo.references.create(branch, tip, force=True)
    repo.set_head(branch)
    repo.reset(tip, pygit2.GIT_RESET_HARD)
    return ArchiveResult(repo_path, added, parked, renamed_from)
