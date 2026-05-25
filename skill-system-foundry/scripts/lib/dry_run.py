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


def planned_line(path: str) -> str:
    """Return the indented human-readable line for a *planned* path.

    Normalises *path* through ``to_posix`` for the same
    platform-independence reason ``write_file`` does for its
    ``Created:`` line.
    """
    return f"  {DRY_RUN_VERB}: {to_posix(path)}"
