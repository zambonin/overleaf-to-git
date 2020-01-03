# -*- coding: utf-8 -*-

from __future__ import absolute_import

from robobrowser import RoboBrowser


def login(browser: RoboBrowser, username: str, password: str):
    browser.open("https://www.overleaf.com/login")
    form = browser.get_form(action="/login")

    form["email"].value = username
    form["password"].value = password

    browser.submit_form(form)
    if browser.url != "https://www.overleaf.com/project":
        # automatic redirection if login was successful
        raise SystemExit("Authentication failed!")
