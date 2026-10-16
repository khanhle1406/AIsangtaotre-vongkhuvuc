"""Package an explicit source allowlist and reject credentials/artifacts."""

import argparse
import hashlib
import os
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from dotenv import dotenv_values


def package(destination: Path | None = None, *, team_name: str | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    if team_name is not None:
        if (
            not team_name
            or team_name.strip() != team_name
            or team_name in {".", ".."}
            or not re.fullmatch(r'[^/\\\x00-\x1f<>:"|?*]+', team_name)
        ):
            raise ValueError(
                "Team name must be a nonempty filename without path separators"
            )
        if destination is not None and destination.name != f"{team_name}.zip":
            raise ValueError("Submission ZIP filename must match the team name")
        destination = destination or root / "dist" / f"{team_name}.zip"
    files = [
        root / "Dockerfile",
        root / ".dockerignore",
        root / "run.py",
        root / "evaluate.py",
        root / "README.md",
        root / "requirements.txt",
        root / "requirements-dev.txt",
        root / "pytest.ini",
        root / ".env.example",
        *sorted((root / "docs").glob("*.md")),
        *sorted((root / "src").glob("*.py")),
        *sorted(
            path
            for path in (root / "tests").glob("*.py")
            if path.name != "test_colab.py"
        ),
        *sorted(
            path
            for path in (root / "benchmarks").glob("*.py")
            if not path.name.startswith("colab_")
        ),
    ]
    destination = destination or root / "dist/table_qa_submission.zip"
    if not destination.is_absolute():
        destination = root / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    secrets = [
        value
        for name, value in dotenv_values(root / ".env").items()
        if value
        and any(term in name.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    ]
    temporary = destination.with_name(destination.name + ".tmp")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
        for file in files:
            body = file.read_bytes()
            if any(secret.encode() in body for secret in secrets):
                raise ValueError(
                    "A credential appears in a source file; archive rejected"
                )
            entry = ZipInfo(
                file.relative_to(root).as_posix(), date_time=(2026, 1, 1, 0, 0, 0)
            )
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, body)
    with ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive integrity check failed")
        expected = {file.relative_to(root).as_posix() for file in files}
        if set(archive.namelist()) != expected:
            raise ValueError("Archive includes unexpected files")
    if temporary.stat().st_size > 100_000_000:
        raise ValueError("Submission ZIP exceeds 100 MB")
    os.replace(temporary, destination)
    print(
        f"{destination.name}: {destination.stat().st_size} bytes; {len(files)} files; sha256={hashlib.sha256(destination.read_bytes()).hexdigest()}"
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-name", required=True, help="Exact registered team name")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    package(args.output_dir / f"{args.team_name}.zip", team_name=args.team_name)


if __name__ == "__main__":
    main()
