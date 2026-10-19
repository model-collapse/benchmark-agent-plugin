# PR: add `python_path` to `experiment()` so task workers can import modules by name

**Branch:** `feat/experiment-python-path` (based on experimaestro-python @ `f7fb7c7`)
**Patch:** `01-experiment-python-path.patch` (apply with `git am`)
**Files:** `src/experimaestro/scheduler/experiment.py` (+16), `src/experimaestro/tests/test_python_path.py` (+58)

## Problem

Task workers reconstruct the task module **by file path**
(`ConfigInformation.fromParameters` → `importlib.util.module_from_spec`) and
their `sys.path` is built only from `PYTHONPATH` in `job.environ` plus
`workspace.python_path` (default `[]`). The launching interpreter's `sys.path`
is not propagated, and `experiment()` exposed no parameter to add import paths
(`project_paths` is only used for git info — verified it does not affect worker
imports).

So a `Task.execute()` that imports a module **by name** at run time — plugin
registries, factories, sibling packages — fails with `ModuleNotFoundError` when
the experiment is driven programmatically through `experiment()`. The only
current workaround is mutating `os.environ["PYTHONPATH"]` before submitting.

## Change

Add `python_path: Optional[list[Union[Path, str]]] = None` to `experiment()`.
Its entries are resolved to absolute paths and appended to
`workspace.python_path`, which the script builder already injects into the
worker's `sys.path`. No behavior change when the argument is omitted.

```python
with experiment(workdir, "demo", python_path=[repo_root]):
    MyTask.C(factory="my_plugins.sub").submit()   # importable in the worker now
```

## Tests

`test_python_path.py`:
- `test_python_path_makes_module_importable_in_worker` — a package written to a
  temp dir (not importable in the parent) is imported by name inside the worker
  via `python_path=[...]`; the job reaches `JobState.DONE`.
- `test_without_python_path_the_worker_cannot_import` — `@pytest.mark.xfail(strict=True)`
  control proving the fix is load-bearing (fails without `python_path`).

Verified green against the branch; `test_tasks.py` + `test_experiment.py` show no
regression (35 passed, 1 pre-existing skip).

## Notes / alternatives

- Could additionally auto-include `Path.cwd()` when `python_path` is unset
  (opt-out) to match the intuition "importable where I launched ⇒ importable in
  the worker". Left out to avoid changing default behavior; happy to add behind a
  flag if preferred.
- Docstring now states explicitly that workers don't inherit the launcher's
  `sys.path`, which was the real surprise.
