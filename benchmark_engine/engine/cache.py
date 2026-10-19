# SPDX-License-Identifier: Apache-2.0
"""On-disk, content-addressed cache for deterministic step artifacts.

Layout: ``<root>/<step>/<sig>/`` holding the artifact plus a ``descriptor.json``.
On load, the stored descriptor is compared to the expected one; a mismatch means
the live/stored artifact is not what the signature promised (e.g. a silently
rebuilt index), raising ``StaleArtifact`` rather than returning a false hit.

Stores are atomic: the producer writes into a temp dir that is renamed into place
only on success, so a failed producer never leaves a visible hit.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable


class StaleArtifact(RuntimeError):
    """Stored descriptor does not match the expected descriptor."""


class SignatureCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _dir(self, step: str, sig: str) -> Path:
        return self.root / step / sig

    def has(self, step: str, sig: str) -> bool:
        return (self._dir(step, sig) / "descriptor.json").exists()

    def path_for(self, step: str, sig: str) -> Path:
        return self._dir(step, sig)

    def store(self, step: str, sig: str, descriptor: dict,
              producer: Callable[[Path], None]) -> Path:
        final = self._dir(step, sig)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=final.parent, prefix=f".{sig}.tmp."))
        try:
            producer(tmp)
            (tmp / "descriptor.json").write_text(json.dumps(descriptor, sort_keys=True))
            if final.exists():
                shutil.rmtree(final)
            tmp.rename(final)
            return final
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def load(self, step: str, sig: str, expect_descriptor: dict) -> Path:
        d = self._dir(step, sig)
        desc_file = d / "descriptor.json"
        if not desc_file.exists():
            raise KeyError(f"no cache entry for {step}/{sig}")
        stored = json.loads(desc_file.read_text())
        if stored != expect_descriptor:
            raise StaleArtifact(
                f"{step}/{sig}: stored descriptor {stored} != expected {expect_descriptor}"
            )
        return d
