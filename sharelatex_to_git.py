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


def format_msg(authors, rev, stamps):
    rev_before, rev_after = stamps['fromV'], stamps['toV']
    desc = "update {}".format(rev)

    if rev_before != rev_after:
        desc += " from r{} to r{}".format(rev_before, rev_after)
    else:
        desc += " to r{}".format(rev_after)

    message = "sharelatex: {}\n".format(desc)
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
        if 'diff' in r['request']['url']:
            key = r['request']['url'].split('doc')[1]
            diffs[key] = loads(r['response']['content']['text'])['diff']

    authors = {}
    for upd in updates:
        for aut in upd['meta']['users']:
            if aut['id'] not in authors.keys():
                if 'last_name' not in aut.keys():
                    name = input("Author name for {}: ".format(
                        aut['first_name'])).rsplit(" ", 1)
                    aut['first_name'], aut['last_name'] = name
                    aut['email'] = input("GitHub email for {}: ".format(
                        aut['email']) or aut['email'])
                authors[aut['id']] = aut

    docs = {}
    for upd in updates:
        names = [to_name(authors[aut['id']]) for aut in upd['meta']['users']]
        key = "/{}/diff?from={}&to={}"
        author, email = names[0].rsplit(" ", 1)
        for k, v in upd['docs'].items():
            try:
                diff = diffs[key.format(k, v['fromV'], v['toV'])]
                if k not in docs.keys():
                    print("Hint: {}".format(str(diff[0])[:40]))
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
    first['message'] = first['message'].rsplit(" ", 2)[0].replace("from", "to")

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
