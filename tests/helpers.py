from overleaf_to_git.custom_types import (
    OverleafProjectWithHistory,
    OverleafRevision,
    OverleafSingleRevision,
)

AUTHOR = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
}


def revision(*file_revs, before=1_700_000_000_000, after=1_700_000_001_000):
    return OverleafRevision(
        authors=[AUTHOR],
        before_ts=before,
        after_ts=after,
        file_revs=list(file_revs),
    )


def project(name="Notes", updates=None):
    if updates is None:
        updates = [
            revision(OverleafSingleRevision("paper.tex", 1, 2, "hello\n", "keep"))
        ]
    return OverleafProjectWithHistory("abc123", name, updates)
