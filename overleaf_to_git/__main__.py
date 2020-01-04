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
)
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

PROJECTS = create_projects(
    BROWSER, ALL_PROJECTS, process_input(len(ALL_PROJECTS))
)
HIST_LENGTHS = [len(project.updates) for project in PROJECTS]
TOTAL_UPDATES = sum(HIST_LENGTHS)

for index, project in enumerate(PROJECTS):
    phist = create_project_history(
        BROWSER, project, sum(HIST_LENGTHS[:index]), TOTAL_UPDATES
    )
