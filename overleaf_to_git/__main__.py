#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=W1632

from __future__ import absolute_import
from getpass import getpass
from typing import List

from robobrowser import RoboBrowser

from .data_composer import (
    create_project_history,
    create_projects,
    create_sequences,
    display_projects,
    OverleafProjectWithHistory,
)
from .git_operations import create_repo
from .overleaf_browser import get_project_list, login


def process_input(limit: int) -> List[int]:
    exceed, sequence = True, []
    while exceed:
        _str = input("Project indices to be processed (e.g. 1-4 7): ")
        sequence = create_sequences(_str)
        exceed = any(num > limit for num in sequence) or not sequence
    return sequence


BROWSER = RoboBrowser(history=True, parser="html.parser")
login(BROWSER, input("Your Overleaf e-mail: "), getpass("Password: "))

ALL_PROJECTS = get_project_list(BROWSER)
print(display_projects(ALL_PROJECTS))

PROJ_QNT = len(ALL_PROJECTS)
INDICES = process_input(PROJ_QNT)

for _ in range(PROJ_QNT + 5):
    # clear one line at a time for every visible project plus input questions
    print("\033[1A\033[2K", end="\r")

PROJECTS = create_projects(BROWSER, ALL_PROJECTS, INDICES)
for index, project in enumerate(PROJECTS):
    phist = create_project_history(BROWSER, project)
    print("\033[2K", end="\r")
    create_repo(OverleafProjectWithHistory(project.uid, project.name, phist))
    print("\033[2K", end="\r")
