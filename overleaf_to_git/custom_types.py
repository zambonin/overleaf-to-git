# -*- coding: utf-8 -*-

from typing import NamedTuple

OverleafAuthor = dict[str, str]
OverleafRawProject = dict[str, str | bool | OverleafAuthor]
OverleafProjectMeta = dict[str, list[OverleafAuthor] | int]
OverleafProjectUpdate = dict[str, int | OverleafProjectMeta | list[str]]
OverleafRawRevision = dict[str, list[dict[str, str]]]


class OverleafProject(NamedTuple):
    uid: str
    name: str
    updates: list[OverleafProjectUpdate]


class OverleafSingleRevision(NamedTuple):
    file_id: str
    before_rev: int
    after_rev: int
    contents: str
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
