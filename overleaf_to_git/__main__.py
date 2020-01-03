#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=W1632

from __future__ import absolute_import
from getpass import getpass

from robobrowser import RoboBrowser

from .data_composer import display_projects
from .overleaf_browser import get_project_list, login


BROWSER = RoboBrowser(history=True, parser="html.parser")

login(BROWSER, input("Your Overleaf e-mail: "), getpass("Password: "))

ALL_PROJECTS = get_project_list(BROWSER)
display_projects(ALL_PROJECTS)
