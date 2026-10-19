# experimaestro — issue/enhancement: task worker doesn't inherit the launcher's import path (no `python_path` on `experiment()`)

**Type:** issue + small enhancement PR
**Version observed:** experimaestro 2.7.0 (Python 3.11)

## Summary

When an experiment is driven programmatically through the `experiment(...)`
context manager, a `Task.execute()` that imports a module **by name at runtime**
(e.g. `importlib.import_module("mypkg.sub")`, a plugin registry, a factory) fails
with `ModuleNotFoundError`, even when that module is importable (editable-install
or on `sys.path`) in the launching process.

Cause: the worker reconstructs the task module **by file path**
(`ConfigInformation.fromParameters` → `importlib.util.module_from_spec`, see
`run.py`), and its `sys.path` is built only from (a) `PYTHONPATH` in
`job.environ` and (b) `job.python_path` ← `workspace.python_path`, which defaults
to `[]` (`scheduler/workspace.py`, `scriptbuilder.py:119-132`). The launching
interpreter's `sys.path`/cwd is **not** propagated, and the `experiment()`
context manager exposes **no** parameter to add import paths. `project_paths` is
*not* it — it is documented as "Paths to the project files (for git info)" and,
confirmed empirically, does not affect the worker's import path.

## Reproduction

```python
import os, json, tempfile
os.environ.pop("PYTHONPATH", None)          # launcher path NOT propagated
from experimaestro import experiment, Task, Param

# task module is importable here (e.g. editable install), but imported *by name*
class Run(Task):
    factory: Param[str]
    def execute(self):
        import importlib
        importlib.import_module(self.factory)   # -> ModuleNotFoundError in worker

with experiment(tempfile.mkdtemp(), "repro"):   # no way to pass import paths
    Run.C(factory="some_sibling_pkg").submit()
```

Workaround that works today (and the only programmatic one found):
```python
os.environ["PYTHONPATH"] = repo_root + os.pathsep + os.environ.get("PYTHONPATH", "")
```
(`experiment(..., project_paths=[repo_root])` does **not** resolve it — verified.)

## Requested change

Make the sanctioned mechanism discoverable from the API that most users touch:

1. **Enhancement:** add `python_path: list[str | Path] | None = None` to
   `experiment(...)`; append it to `workspace.python_path` (which `scriptbuilder`
   already injects into the worker's `sys.path`). ~5 lines.
2. **Optional:** when `python_path` is unset, auto-include `Path.cwd()` (opt-out),
   matching the intuition that a task importable where you launched it stays
   importable in the worker.
3. **Docs:** state explicitly that workers do not inherit the launcher's
   `sys.path`; list the three levers (`PYTHONPATH`, experiments-CLI `pythonpath`
   config, and the new `experiment(python_path=...)`).

Happy to send the PR (parameter + docs) if the maintainers prefer option 1.
