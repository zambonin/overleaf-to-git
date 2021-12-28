#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0413

from __future__ import absolute_import

from browser_cookie3 import firefox as get_cookies_from_browser
from requests import session
import werkzeug

werkzeug.cached_property = werkzeug.utils.cached_property
from robobrowser import RoboBrowser


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


SESSION = session()
SESSION.cookies = get_cookies_from_browser(domain_name="overleaf.com")
BROWSER = RoboBrowser(
    history=True,
    parser="html.parser",
    user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:95.0) Gecko/20100101 Firefox/95.0",
    session=SESSION,
)

ALL_PROJECTS = get_project_list(BROWSER)
print(display_projects(ALL_PROJECTS))

PROJ_QNT = len(ALL_PROJECTS)
try:
    INDICES = process_input(PROJ_QNT)
except KeyboardInterrupt as e:
    print("\033[2K", end="\r")
    raise SystemExit("Program aborted by user!") from e
finally:
    for _ in range(PROJ_QNT + 5):
        # clear one line at a time for every visible project plus input questions
        print("\033[1A\033[2K", end="\r")

PROJECTS = create_projects(BROWSER, ALL_PROJECTS, INDICES)
for index, project in enumerate(PROJECTS):
    history = create_project_history(BROWSER, project)
    print("\033[2K", end="\r")
    create_repo(history)
    print("\033[2K", end="\r")
