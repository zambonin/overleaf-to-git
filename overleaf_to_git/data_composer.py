# -*- coding: utf-8 -*-

from __future__ import absolute_import
from textwrap import shorten
from typing import Any, Dict, List


def display_projects(projects: List[Dict[str, Any]]) -> str:
    output = ""
    line_fmt = "{:>4}  {:<34}  {:<22}  {:<10}\n"
    output += line_fmt.format("", "Project name", "Owner", "Last update")

    for index, project in enumerate(projects):
        email = project["owner"]["email"]
        output += line_fmt.format(
            index + 1,
            shorten(project["name"], width=34, placeholder="..."),
            (email[:18] + "...") if len(email) > 20 else email,
            project["lastUpdated"][:10],
        )

    return output


def create_sequences(string: str) -> List[int]:
    raw_numbers = string.replace("-", " ").split()
    ranges = [seq.split("-") for seq in string.split()]

    all_numbers = all(num.isdigit() for num in raw_numbers)
    any_zero = "0" in raw_numbers
    any_long_seq = any(len(seq) > 2 for seq in ranges)
    any_incomplete_seq = any("" in seq for seq in ranges)

    if not all_numbers or any_zero or any_long_seq or any_incomplete_seq:
        return []

    sequence = set()
    for item in ranges:
        numbers = list(map(int, item))
        sequence |= set(range(min(numbers), max(numbers) + 1))

    return sorted(sequence)
