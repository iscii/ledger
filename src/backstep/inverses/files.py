"""
backstep.inverses.files
~~~~~~~~~~~~~~~~~~~~~~~
Built-in inverse pack for common filesystem tool operations.

This is the reference implementation of a backstep.inverses plugin — it
shows plugin authors exactly what to copy.

Registered inverses
-------------------
  write_file   → delete the file at args["path"]
  delete_file  → restore file from result["previous_content"]
  create_dir   → remove dir at args["path"] (only if empty)
  move_file    → move back from args["dest"] to args["src"]
  append_file  → truncate file to result["original_size"] bytes
"""

from __future__ import annotations

import os
import shutil

from backstep.registry import registry

_SOURCE = "backstep_files (built-in)"


# ---------------------------------------------------------------------------
# write_file — inverse: delete the created file
# ---------------------------------------------------------------------------

def _undo_write_file(args: dict, result: dict) -> None:  # noqa: ARG001
    path = args["path"]
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# delete_file — inverse: restore from result["previous_content"]
# ---------------------------------------------------------------------------

def _undo_delete_file(args: dict, result: dict) -> None:
    previous = result.get("previous_content")
    if previous is None:
        raise ValueError(
            "Cannot undo delete_file: result missing 'previous_content'. "
            "Ensure your delete_file tool returns the original file contents."
        )
    with open(args["path"], "w", encoding="utf-8") as fh:
        fh.write(previous)


# ---------------------------------------------------------------------------
# create_dir — inverse: remove the directory (only if empty)
# ---------------------------------------------------------------------------

def _undo_create_dir(args: dict, result: dict) -> None:  # noqa: ARG001
    path = args["path"]
    try:
        os.rmdir(path)  # raises OSError if non-empty — intentional
    except OSError:
        pass


# ---------------------------------------------------------------------------
# move_file — inverse: move back from dest to src
# ---------------------------------------------------------------------------

def _undo_move_file(args: dict, result: dict) -> None:  # noqa: ARG001
    src = args["src"]
    dest = args["dest"]
    if os.path.exists(dest):
        shutil.move(dest, src)


# ---------------------------------------------------------------------------
# append_file — inverse: truncate to original size
# ---------------------------------------------------------------------------

def _undo_append_file(args: dict, result: dict) -> None:  # noqa: ARG001
    original_size = result.get("original_size")
    if original_size is None:
        raise ValueError(
            "Cannot undo append_file: result missing 'original_size'. "
            "Ensure your append_file tool returns the original file size in bytes."
        )
    path = args["path"]
    with open(path, "a+b") as fh:
        fh.truncate(int(original_size))


# ---------------------------------------------------------------------------
# Register everything
# ---------------------------------------------------------------------------

registry.register("write_file",  _undo_write_file,  source=_SOURCE)
registry.register("delete_file", _undo_delete_file, source=_SOURCE)
registry.register("create_dir",  _undo_create_dir,  source=_SOURCE)
registry.register("move_file",   _undo_move_file,   source=_SOURCE)
registry.register("append_file", _undo_append_file, source=_SOURCE)
