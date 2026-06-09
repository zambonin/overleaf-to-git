#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0413

from __future__ import absolute_import

from pathlib import Path
from tempfile import gettempdir

from .client import OverleafClient
from .data_composer import (
    create_project_history,
    create_projects,
    create_sequences,
    display_projects,
)
from .git_operations import create_repo
from .overleaf_browser import get_project_list


def process_input(limit: int) -> list[int]:
    exceed, sequence = True, []
    while exceed:
        _str = input("Project indices to be processed (e.g. 1-4 7): ")
        sequence = create_sequences(_str)
        exceed = any(num > limit for num in sequence) or not sequence
    return sequence


CLIENT = OverleafClient(cache_dir=Path(gettempdir()) / "overleaf-to-git")
CLIENT.load_browser_cookies("firefox")

ALL_PROJECTS = get_project_list(CLIENT)
print(display_projects(ALL_PROJECTS))

PROJ_QNT = len(ALL_PROJECTS)
try:
    INDICES = process_input(PROJ_QNT)
except KeyboardInterrupt as e:
    print("\033[2K", end="\r")
    raise SystemExit("Program aborted by user!") from e
finally:
    for _ in range(PROJ_QNT + 5):
        print("\033[1A\033[2K", end="\r")

PROJECTS = create_projects(CLIENT, ALL_PROJECTS, INDICES)
for index, project in enumerate(PROJECTS):
    history = create_project_history(CLIENT, project)
    print("\033[2K", end="\r")
    create_repo(history)
    print("\033[2K", end="\r")
