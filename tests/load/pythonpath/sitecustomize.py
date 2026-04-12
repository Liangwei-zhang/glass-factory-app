from __future__ import annotations

from pathlib import Path
import sys


def _patch_zope_namespace() -> None:
    module = sys.modules.get("zope")
    if module is None:
        return

    namespace_paths = getattr(module, "__path__", None)
    if namespace_paths is None:
        return

    for path_entry in sys.path:
        candidate = Path(path_entry) / "zope"
        if not candidate.is_dir():
            continue
        if not (candidate / "event").is_dir():
            continue

        candidate_str = str(candidate)
        if candidate_str not in namespace_paths:
            namespace_paths.append(candidate_str)


_patch_zope_namespace()