# Writing a Backstep Plugin

Backstep auto-discovers plugins at import time via two mechanisms:

1. **Naming convention** — any installed package whose name starts with `backstep_`
2. **Entry points** — packages that declare a `backstep.inverses`, `backstep.adapters`,
   or `backstep.reporters` entry point

---

## Inverse pack example

Create a package named `backstep_mytool`:

```python
# backstep_mytool/__init__.py
import backstep

@backstep.register_inverse("my_tool_name")
def undo_my_tool(args: dict, result: dict) -> None:
    # Reverse whatever my_tool did.
    # args  — the original tool input dict
    # result — the tool result dict captured by backstep
    pass

@backstep.committed("my_irreversible_tool")
def mark_irreversible(args: dict, result: dict) -> None:
    pass  # body unused; decorator marks the tool as committed
```

---

## Publishing

Name your package `backstep-*` on PyPI (hyphens in the PyPI name,
underscores in the import name):

```
pip install backstep-mytool
```

Backstep discovers and loads it automatically on next import — no
configuration required by the end user.

---

## Listing loaded plugins

```
$ backstep plugins
Loaded plugins:
  backstep_files (built-in)   inverses: write_file, delete_file, create_dir, move_file, append_file
  backstep_mytool              inverses: my_tool_name
```

---

## Reference implementation

See `src/backstep/inverses/files.py` for the built-in file inverse pack.
