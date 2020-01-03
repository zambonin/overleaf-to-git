#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=W1632

from __future__ import absolute_import
from getpass import getpass

from robobrowser import RoboBrowser

from .overleaf_browser import login

login(
    RoboBrowser(history=True, parser="html.parser"),
    input("Your Overleaf e-mail: "),
    getpass("Password: "),
)
