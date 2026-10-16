"""Package an explicit source allowlist and reject credentials/artifacts."""

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from dotenv import dotenv_values


def package() -> Path:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "run.py",
        root / "evaluate.py",
        root / "README.md",
        root / "requirements.txt",
        root / "requirements-dev.txt",
        root / ".env.example",
        *sorted((root / "src").glob("*.py")),
        *sorted((root / "tests").glob("*.py")),
        *sorted((root / "benchmarks").glob("*.py")),
    ]
    destination = root / "dist/table_qa_submission.zip"
    destination.parent.mkdir(exist_ok=True)
    secrets = [
        value
        for name, value in dotenv_values(root / ".env").items()
        if value
        and any(term in name.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    ]
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
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
    with ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive integrity check failed")
        expected = {file.relative_to(root).as_posix() for file in files}
        if set(archive.namelist()) != expected:
            raise ValueError("Archive includes unexpected files")
    if destination.stat().st_size >= 100_000_000:
        raise ValueError("Submission ZIP exceeds 100 MB")
    print(
        f"{destination.name}: {destination.stat().st_size} bytes; {len(files)} files; sha256={hashlib.sha256(destination.read_bytes()).hexdigest()}"
    )
    return destination


if __name__ == "__main__":
    package()
