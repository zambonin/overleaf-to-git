# -*- coding: utf-8 -*-

from __future__ import absolute_import
from json import loads
from operator import itemgetter

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


def get_project_list(browser: RoboBrowser):
    raw_json = browser.find(id="data").text
    dict_json = loads(raw_json)["projects"]
    return sorted(dict_json, key=itemgetter("lastUpdated"), reverse=True)
