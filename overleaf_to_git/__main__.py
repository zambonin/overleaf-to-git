#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from math import isfinite
from os import environ
from pathlib import Path

import requests

from .client import (
    DEFAULT_BASE_URL,
    DEFAULT_COOKIE_NAME,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    OverleafClient,
)
from .custom_types import ArchiveResult
from .data_composer import (
    create_project,
    create_project_history,
    create_sequences,
    display_projects,
    match_tags,
)
from .git_operations import create_repo
from .overleaf_browser import get_dashboard
from .progress import STATUS, Progress

DEFAULT_CACHE_DIR = (
    Path(environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "overleaf-to-git"
)
DEFAULT_OUTPUT_DIR = (
    Path(environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "overleaf-to-git"
)


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="overleaf-to-git",
        description="Archive Overleaf project history into Git repositories.",
    )
    parser.add_argument(
        "--base-url",
        default=environ.get("OVERLEAF_URL", DEFAULT_BASE_URL),
        help="Overleaf base URL (default: %(default)s); set your domain for "
        "a self-hosted instance.",
    )

    auth = parser.add_argument_group("authentication")
    auth.add_argument(
        "--session",
        default=environ.get("OVERLEAF_SESSION"),
        help="session cookie value, copied from your browser "
        "(or via env OVERLEAF_SESSION).",
    )
    auth.add_argument(
        "--cookie-name",
        default=DEFAULT_COOKIE_NAME,
        help="session cookie name (default: %(default)s; self-hosted "
        "instances often use sharelatex.sid).",
    )
    auth.add_argument(
        "--from-browser",
        metavar="BROWSER",
        default=None,
        help="optional: import cookies from a browser via browser_cookie3 "
        "(e.g. firefox, chrome). Requires the 'browser' extra.",
    )

    parser.add_argument(
        "--projects",
        metavar="SPEC",
        default=None,
        help='non-interactive selection, e.g. "1-4 7"; omit to choose interactively.',
    )
    parser.add_argument(
        "--project-id",
        action="append",
        dest="project_ids",
        default=None,
        metavar="ID",
        help="archive the project with this stable Overleaf id; repeatable",
    )
    parser.add_argument(
        "--tag",
        metavar="NAME",
        action="append",
        dest="tags",
        default=None,
        help="archive every project carrying this dashboard tag; repeatable, "
        "and unioned with --projects.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory to create the Git repositories in (default: %(default)s).",
    )
    parser.add_argument(
        "--group-by-tag",
        action="store_true",
        help="write repositories into output-dir/<tag>/; a project with "
        "several tags lands under the first one.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="persistent download cache; makes runs resumable (default: %(default)s).",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="HTTP User-Agent header.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="per-request timeout (default: %(default)s). ZIP downloads get "
        "longer, since Overleaf assembles them before sending a byte.",
    )
    parser.add_argument(
        "--retries",
        type=nonnegative_int,
        default=DEFAULT_RETRIES,
        metavar="N",
        help="transport-level retries for timeouts, resets and gateway "
        "errors, with exponential backoff (default: %(default)s).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list available projects and exit.",
    )
    return parser.parse_args(argv)


def build_client(args: argparse.Namespace) -> OverleafClient:
    client = OverleafClient(
        args.base_url,
        cache_dir=args.cache_dir,
        user_agent=args.user_agent,
        timeout=args.timeout,
        retries=args.retries,
    )
    if args.from_browser:
        client.load_browser_cookies(args.from_browser)
    if args.session:
        client.set_session_cookie(args.session, args.cookie_name)
    if not client.authenticated():
        raise SystemExit(
            "No credentials. Pass --session (or set OVERLEAF_SESSION) with the "
            "session cookie from your browser, or --from-browser firefox."
        )
    return client


def choose_indices(total: int) -> list[int]:
    while True:
        try:
            raw = input("Project indices to archive (e.g. 1-4 7): ")
        except (EOFError, KeyboardInterrupt) as exc:
            raise SystemExit("\nAborted by user.") from exc
        sequence = create_sequences(raw)
        if sequence and not any(num > total for num in sequence):
            return sequence
        print("Invalid selection; try again.")


def select_indices(args: argparse.Namespace, all_projects, all_tags) -> list[int]:
    chosen: set[int] = set()
    if args.project_ids:
        wanted = set(args.project_ids)
        by_id = {
            project["id"]: index for index, project in enumerate(all_projects, start=1)
        }
        missing = sorted(wanted - set(by_id))
        if missing:
            raise SystemExit(
                "Unknown Overleaf project id(s): {}".format(", ".join(missing))
            )
        chosen |= {by_id[project_id] for project_id in wanted}
    if args.tags:
        chosen |= set(match_tags(all_projects, all_tags, args.tags))
    if args.projects is not None:
        indices = create_sequences(args.projects)
        if not indices or any(num > len(all_projects) for num in indices):
            raise SystemExit("Invalid --projects selection.")
        chosen |= set(indices)

    if args.tags and not chosen:
        raise SystemExit("No projects carry the requested tag(s).")
    if chosen:
        return sorted(chosen)
    return choose_indices(len(all_projects))


def shell_path(path: Path) -> str:
    for name in ("XDG_DATA_HOME", "HOME"):
        root = environ.get(name)
        if not root:
            continue
        try:
            return "${}/{}".format(name, path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def summarize(results: list[tuple[str, ArchiveResult]]) -> None:
    changed = [res for _, res in results if res.changed]
    print(
        "{} project{}, {} updated{}".format(
            len(results),
            "" if len(results) == 1 else "s",
            len(changed) or "none",
            ":" if changed else "",
        )
    )
    for res in changed:
        notes = []
        if res.added:
            notes.append(
                "+{} commit{}".format(res.added, "" if res.added == 1 else "s")
            )
        if res.renamed_from:
            notes.append("renamed from {}".format(res.renamed_from))
        if res.parked:
            notes.append("kept local commits on {!r}".format(res.parked))
        print("  {}".format(shell_path(res.path)))
        print("    {}".format(", ".join(notes)))


def archive(args: argparse.Namespace) -> None:
    client = build_client(args)

    all_projects, all_tags = get_dashboard(client)
    picking = args.projects is None and not args.tags and not args.project_ids
    if args.list or picking:
        print(display_projects(all_projects, all_tags), end="")
    if args.list or not all_projects:
        return

    indices = select_indices(args, all_projects, all_tags)
    chosen = [all_projects[index - 1] for index in indices]
    progress = Progress(len(chosen))
    results: list[tuple[str, ArchiveResult]] = []

    for position, raw_project in enumerate(chosen, start=1):
        progress.project(position, raw_project["name"])
        project = create_project(client, raw_project, all_tags, progress)
        history = create_project_history(client, project, progress)
        result = create_repo(history, args.output_dir, args.group_by_tag, progress)
        results.append((project.name, result))
        if not STATUS.interactive:
            STATUS.result("Archived {!r} -> {}".format(project.name, result.path))

    progress.done()
    if STATUS.interactive:
        summarize(results)


def main(argv=None) -> None:
    args = parse_args(argv)
    try:
        archive(args)
    except requests.RequestException as exc:
        raise SystemExit("Overleaf request failed: {}".format(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit(
            "\n\033[2K\rInterrupted. Rerun to resume from the cache in {}.".format(
                args.cache_dir
            )
        ) from None


if __name__ == "__main__":
    main()
