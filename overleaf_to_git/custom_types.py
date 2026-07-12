# -*- coding: utf-8 -*-

from pathlib import Path
from typing import NamedTuple

OverleafAuthor = dict[str, str]
OverleafRawProject = dict[str, str | bool | OverleafAuthor]
OverleafProjectMeta = dict[str, list[OverleafAuthor] | int]
OverleafProjectUpdate = dict[str, int | OverleafProjectMeta | list[str]]
OverleafRawRevision = dict[str, list[dict[str, str]]]


class OverleafTag(NamedTuple):
    uid: str
    name: str
    project_ids: frozenset[str]


class OverleafProject(NamedTuple):
    uid: str
    name: str
    updates: list[OverleafProjectUpdate]
    tags: tuple[str, ...] = ()


class OverleafSingleRevision(NamedTuple):
    file_id: str
    before_rev: int
    after_rev: int
    contents: str | bytes
    operation: str


class OverleafRevision(NamedTuple):
    authors: list[OverleafAuthor]
    before_ts: int
    after_ts: int
    file_revs: list[OverleafSingleRevision]


class OverleafProjectWithHistory(NamedTuple):
    uid: str
    name: str
    updates: list[OverleafRevision]
    tags: tuple[str, ...] = ()


class ArchiveResult(NamedTuple):
    path: Path
    added: int = 0
    parked: str | None = None
    renamed_from: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.parked or self.renamed_from)
