#!/usr/bin/env python
# -*- coding: utf-8 -*-


import json
from datetime import datetime
from subprocess import Popen, PIPE
from os import environ
from sys import argv


def to_date(stamp):
    return datetime.fromtimestamp(stamp / 1000).astimezone().strftime("%c %z")


def to_name(aut):
    return '{} {} <{}>'.format(aut['first_name'], aut['last_name'], aut['email'])


def format_msg(authors, rev, stamps):
    rev_before, rev_after = stamps['fromV'], stamps['toV']
    desc = "update {}".format(rev)

    if rev_before != rev_after:
        desc += " from r{} to r{}".format(rev_before, rev_after)
    else:
        desc += " to r{}".format(rev_after)

    message = "sharelatex: {}\n".format(desc)
    message += "".join("\nCo-authored-by: {}\n".format(co) for co in authors[1:])

    return message


def get_changes(_type):
    content = ""
    for d in diff:
        for t in "u" + _type:
            try:
                content += d[t]
            except KeyError:
                pass
    return content


with open(argv[1]) as h:
    dh = json.load(h)['log']

    updates = []
    diffs = {}
    commits = []

    for r in dh['entries']:
        if 'updates' in r['request']['url']:
            updates += json.loads(r['response']['content']['text'])['updates']
        if 'diff' in r['request']['url']:
            key = r['request']['url'].split('doc')[1]
            diffs[key] = json.loads(r['response']['content']['text'])['diff']

    docs = {}
    dates = []
    for upd in updates:
        names = [to_name(aut) for aut in upd['meta']['users']]
        key = "/{}/diff?from={}&to={}"
        author, email = names[0].rsplit(" ", 1)
        for k, v in upd['docs'].items():
            diff = diffs[key.format(k, v['fromV'], v['toV'])]
            if k not in docs.keys():
                print("Hint: {}".format(diff[0]))
                docs[k] = input("Real name of document {}: ".format(k))
            commits.append({
                'author': author,
                'author_email': email[1:-1],
                'author_date': to_date(upd['meta']['start_ts']),
                'commit_date': to_date(upd['meta']['end_ts']),
                'message': format_msg(names, docs[k], v),
                'before': get_changes(diff, 'd'),
                'after': get_changes(diff, 'i'),
            })

    # TODO initialize git repo inside new folder

    first = commits[-1].copy()
    first['commit_date'] = first['author_date']
    first['after'] = first.pop('before')
    first['message'] = first['message'].rsplit(" ", 2)[0].replace("from", "to")

    new_env = environ.copy()
    for commit in [first] + commits[::-1]:
        new_env['GIT_AUTHOR_NAME'] = commit['author']
        new_env['GIT_AUTHOR_EMAIL'] = commit['author_email']
        new_env['GIT_AUTHOR_DATE'] = commit['author_date']
        new_env['GIT_COMMITTER_DATE'] = commit['commit_date']

        filename = commit['message'].split()[2]
        with open(filename, 'w') as f:
            f.write(commit['after'])

        add_cmd = f"git add {filename}"
        commit_cmd = f"git  commit  --message  {commit['message']}"

        Popen(add_cmd.split(), stdout=PIPE).communicate()
        Popen(commit_cmd.split("  "), stdout=PIPE, env=new_env).communicate()
