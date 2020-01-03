# -*- coding: utf-8 -*-

from __future__ import absolute_import
from textwrap import shorten
from typing import Dict


def display_projects(projects: Dict):
    line_fmt = "{:>4}  {:<34}  {:<22}  {:<10}"
    print(line_fmt.format("", "Project name", "Owner", "Last update"))

    for index, project in enumerate(projects):
        email = project["owner"]["email"]
        print(
            line_fmt.format(
                index + 1,
                shorten(project["name"], width=34, placeholder="..."),
                (email[:18] + "...") if len(email) > 20 else email,
                project["lastUpdated"][:10],
            )
        )
