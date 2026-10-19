# experimaestro — PR: don't log a WARNING for git info outside a git repository

**Type:** small robustness PR
**Version observed:** experimaestro 2.7.0
**File:** `experimaestro/utils/git.py` (~line 128)

## Summary

Running any experiment from a directory that is not a git repository prints, on
every run:

```
Error getting git info: Command '['git', 'rev-parse', 'HEAD']' returned non-zero exit status 128.
```

Git metadata capture is best-effort (it's for provenance), and "not a git
repository" is an expected, benign condition — not a warning-worthy error. It is
noisy (fires repeatedly, e.g. once per worker) and alarming to users.

## Current code

```python
    except FileNotFoundError:
        logger.debug("Git command not found")
        return None
    except subprocess.CalledProcessError as e:
        logger.warning("Error getting git info: %s", e)   # <- line ~128
        return None
```

## Proposed change

Treat a non-zero git exit as a debug-level, expected outcome (git info is
optional), reserving warnings for genuinely unexpected failures:

```python
    except FileNotFoundError:
        logger.debug("Git command not found")
        return None
    except subprocess.CalledProcessError as e:
        # Not a git repo / no commits yet is an expected, benign condition.
        # Git metadata is best-effort provenance, so keep this quiet.
        logger.debug("Git info unavailable (%s)", e)
        return None
```

(If finer granularity is wanted: inspect `e.returncode == 128` / stderr for
"not a git repository" and only `debug` that case, keeping `warning` for others.)

One-line change; no behavior change beyond log level. Happy to PR.
