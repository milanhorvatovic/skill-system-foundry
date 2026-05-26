"""Dry-run helpers for the scaffold entry point.

Scaffold's ``--dry-run`` flag previews every filesystem mutation without
touching disk.  The two write primitives (``write_file`` and
``create_dir_with_gitkeep``) consult :data:`DRY_RUN_VERB` only for the
human-readable verb; the suppression itself is driven by the ``dry_run``
argument threaded through them.  Keeping the verb constant and the
``Would create:`` formatter here means the entry point stays a thin
wrapper and the wording lives in one place.

No filesystem state is held in this module — the caller owns the list of
planned paths (scaffold already accumulates them in ``created_paths``).
This module is pure formatting so it carries no ``print`` or
``sys.exit`` (those belong to the entry point and ``reporting.py``).
"""

from .reporting import to_posix

# Verb used in the human-readable line for a path that *would* be
# created in dry-run mode, mirroring the real-run "Created:" verb.
DRY_RUN_VERB = "Would create"

# Verb for an existing file a real run would modify in place rather than
# create — e.g. an existing manifest.yaml that an append updates. Mirrors
# the real-run "Updated:" verb so a dry run never claims a file that
# already exists would be created.
DRY_RUN_UPDATE_VERB = "Would update"


def _planned_line(verb: str, path: str) -> str:
    """Return the indented ``  <verb>: <path>`` line for *path*.

    Normalises *path* through ``to_posix`` for the same
    platform-independence reason ``write_file`` does for its
    ``Created:`` line.
    """
    return f"  {verb}: {to_posix(path)}"


def planned_line(path: str) -> str:
    """Return the indented human-readable line for a *planned* path."""
    return _planned_line(DRY_RUN_VERB, path)


def planned_update_line(path: str) -> str:
    """Return the indented line for a path a real run would *update*.

    Used for an existing manifest under ``--dry-run``: a real run
    appends to it and reports ``Updated:`` instead of ``Created:``, so
    the preview must report it as an update and must not list it among
    the paths a real run would create.
    """
    return _planned_line(DRY_RUN_UPDATE_VERB, path)
