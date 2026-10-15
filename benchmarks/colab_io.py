"""Standard-library-only persistence, usable before Colab dependencies install."""

import json
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(path)


def export_results(session: Path) -> Path:
    destination = session / "results.zip"
    temporary = session / "results.tmp.zip"
    with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
        for path in sorted(session.rglob("*")):
            if path.is_file() and path.suffix in {".json", ".csv", ".md", ".log"}:
                archive.write(path, path.relative_to(session))
    temporary.replace(destination)
    return destination
