#!/usr/bin/env python
# -*- coding: utf-8 -*-


from datetime import datetime
from json import load, loads
from subprocess import Popen, PIPE
from os import environ
from sys import argv


def to_date(stamp):
    return datetime.fromtimestamp(stamp / 1000).astimezone().strftime("%c %z")


def to_name(aut):
    return '{} {} <{}>'.format(aut['first_name'], aut['last_name'], aut['email'])


def format_msg(authors, rev, before, after):
    desc = "update {}".format(rev)

    if before != after:
        desc += " from r{} to r{}".format(before, after)
    else:
        desc += " to r{}".format(after)

    message = "overleaf: {}\n".format(desc)
    message += "".join("\nCo-authored-by: {}".format(co) for co in authors[1:])

    return message


def get_changes(diff, _type):
    content = ""
    for d in diff:
        for t in "u" + _type:
            try:
                content += d[t]
            except KeyError:
                pass
    return content


with open(argv[1]) as h:
    dh = load(h)['log']

    updates = []
    diffs = {}
    commits = []

    for r in dh['entries']:
        if 'updates' in r['request']['url']:
            updates += loads(r['response']['content']['text'])['updates']
        if 'path' in r['request']['url']:
            key = r['request']['url'].split('?')[1]
            diffs[key] = loads(r['response']['content']['text'])['diff']

    authors = {}
    for upd in updates:
        for aut in upd['meta']['users']:
            if aut['id'] not in authors.keys():
                if not aut['last_name']:
                    name = input("Author name for {}: ".format(
                        aut['first_name'])).rsplit(" ", 1)
                    aut['first_name'], aut['last_name'] = name
                    aut['email'] = input("GitHub email for {}: ".format(
                        aut['email'])) or aut['email']
                authors[aut['id']] = aut

    for upd in updates:
        names = [to_name(authors[aut['id']]) for aut in upd['meta']['users']]
        key = "pathname={}&from={}&to={}"
        author, email = names[0].rsplit(" ", 1)
        for path in upd['pathnames']:
            try:
                diff = diffs[key.format(path, upd['toV'], upd['toV'])]
                commits.append({
                    'author': author,
                    'author_email': email[1:-1],
                    'author_date': to_date(upd['meta']['start_ts']),
                    'commit_date': to_date(upd['meta']['end_ts']),
                    'message': format_msg(names, path, upd['fromV'], upd['toV']),
                    'before': get_changes(diff, 'd'),
                    'after': get_changes(diff, 'i'),
                })
            except KeyError:
                pass

    commits = sorted(
            [dict(t) for t in set([tuple(d.items()) for d in commits])],
            key = lambda k: datetime.strptime(k['author_date'], "%c %z"),
            reverse=True)

    Popen("git init".split(), stdout=PIPE).communicate()

    first = commits[-1].copy()
    first['commit_date'] = first['author_date']
    first['after'] = first.pop('before')

    new_env = environ.copy()
    for commit in [first] + commits[::-1]:
        new_env['GIT_AUTHOR_NAME'] = commit['author']
        new_env['GIT_AUTHOR_EMAIL'] = commit['author_email']
        new_env['GIT_AUTHOR_DATE'] = commit['author_date']
        new_env['GIT_COMMITTER_NAME'] = commit['author']
        new_env['GIT_COMMITTER_EMAIL'] = commit['author_email']
        new_env['GIT_COMMITTER_DATE'] = commit['commit_date']

        filename = commit['message'].split()[2]
        with open(filename, 'w') as f:
            f.write(commit['after'])

        add_cmd = f"git add {filename}"
        commit_cmd = f"git  commit  --message  {commit['message']}"

        Popen(add_cmd.split(), stdout=PIPE).communicate()
        Popen(commit_cmd.split("  "), stdout=PIPE, env=new_env).communicate()
