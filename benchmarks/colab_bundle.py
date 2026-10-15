"""Build a secret-free development bundle and a portable Run-All Colab notebook."""

import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import dotenv_values

from .fixtures import generate_fixtures


def dataset_copy(source: Path, target: Path, references: str) -> None:
    target.mkdir(parents=True)
    shutil.copytree(source / "xlsx_files", target / "xlsx_files")
    shutil.copy2(source / "queries.json", target / "queries.json")
    shutil.copy2(source / references, target / "references.csv")


def notebook() -> dict[str, Any]:
    cells: list[dict[str, Any]] = []

    def add(kind: str, text: str) -> None:
        cell: dict[str, Any] = {
            "cell_type": kind,
            "metadata": {},
            "source": text.splitlines(keepends=True),
        }
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)

    add(
        "markdown",
        """# Qwen 4B / T4: kiểm thử pipeline trong 45 phút
Chọn **Runtime → Change runtime type → T4 GPU**. Dùng tài khoản Colab của bạn.
Notebook tải Qwen chính thức, nén NF4, chạy benchmark trên loopback và lưu Drive.
Không nhập API key. Model nhỏ không bảo đảm dự đoán được điểm Qwen3.7 Flash.
Tải lên `table_qa_colab_dev.zip` khi được hỏi; không upload `.env`.
Thời gian 45 phút bắt đầu sau xác thực Drive/nhập gói, trước cài thư viện và tải model.
""",
    )
    add(
        "code",
        """# Kết nối Drive và nhập gói phát triển (không cần khóa API)
from google.colab import drive, files
from pathlib import Path
drive.mount('/content/drive')
DRIVE_ROOT = Path('/content/drive/MyDrive/TableQA_T4')
DRIVE_ROOT.mkdir(parents=True, exist_ok=True)
BUNDLE = DRIVE_ROOT / 'table_qa_colab_dev.zip'
if not BUNDLE.exists():
    uploaded = files.upload()
    if 'table_qa_colab_dev.zip' not in uploaded:
        raise ValueError('Hãy chọn table_qa_colab_dev.zip')
    BUNDLE.write_bytes(uploaded['table_qa_colab_dev.zip'])
""",
    )
    add(
        "code",
        """# Bắt đầu phiên 45 phút; mọi kết quả lưu trong một thư mục Drive mới
import hashlib, json, os, shutil, stat, subprocess, sys, time, zipfile
STARTED = time.time()
SESSION = DRIVE_ROOT / time.strftime('session_%Y%m%d_%H%M%S', time.gmtime(STARTED))
SESSION.mkdir(exist_ok=False)
WORK = Path('/content/table_qa_t4_' + str(int(STARTED)))
WORK.mkdir(exist_ok=False)
with zipfile.ZipFile(BUNDLE) as archive:
    if sum(i.file_size for i in archive.infolist()) > 100_000_000:
        raise ValueError('Gói vượt 100 MB')
    manifest = json.loads(archive.read('bundle_manifest.json'))
    for item in archive.infolist():
        target = (WORK / item.filename).resolve()
        if not target.is_relative_to(WORK.resolve()) or stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('Đường dẫn ZIP không hợp lệ')
        if item.filename != 'bundle_manifest.json':
            if hashlib.sha256(archive.read(item)).hexdigest() != manifest['files'].get(item.filename):
                raise ValueError('Hash file không khớp')
    archive.extractall(WORK)
os.chdir(WORK)
# Để resume sau mất runtime: điền thư mục session cũ, không tự mở phiên mới.
RESUME_FROM = ''
if RESUME_FROM:
    for old in Path(RESUME_FROM).glob('*'):
        if old.is_dir() and (old / 'checkpoint.json').exists():
            shutil.copytree(old, SESSION / old.name)
    if (Path(RESUME_FROM) / 'selection.json').exists():
        shutil.copy2(Path(RESUME_FROM) / 'selection.json', SESSION / 'selection.json')
with (SESSION / 'bootstrap.log').open('w') as output:
    job = subprocess.Popen([sys.executable, '-m', 'benchmarks.colab_bootstrap',
        '--session-dir', str(SESSION), '--started', str(STARTED)], stdout=output, stderr=subprocess.STDOUT)
print('Session:', SESSION)
""",
    )
    add(
        "code",
        """# Theo dõi, dừng đúng hạn và giải phóng model khi kết thúc
try:
    while job.poll() is None and time.time() < STARTED + 2700:
        state_file = SESSION / 'job.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else {'status': 'starting'}
        print(time.strftime('%H:%M:%S'), state['status'], flush=True)
        time.sleep(15)
finally:
    if job.poll() is None:
        job.terminate()
        try:
            job.wait(timeout=10)
        except subprocess.TimeoutExpired:
            job.kill()
            job.wait(timeout=5)
    # Bootstrap normally already stopped its children. Recover after an interruption.
    import psutil
    for process in psutil.Process().children(recursive=True):
        try:
            command = process.cmdline()
            if 'benchmarks.colab_server' in command and str(SESSION) in command:
                process.terminate()
        except psutil.NoSuchProcess:
            print('Model process already exited')
    from benchmarks.colab_io import export_results
    print('Kết quả:', export_results(SESSION))
    if (SESSION / 'summary.json').exists():
        print((SESSION / 'summary.json').read_text()[:12000])
""",
    )
    add(
        "markdown",
        """Kết quả local nằm trong `summary.json`, CSV và checkpoint từng stage.
Chỉ so sánh các stage có `complete=true`. Holdout chạy sau khi khóa `selection.json`.
Nếu hết giờ/quota hoặc setup lỗi, xem `job.json`, `install.log`, `server.log`.
Kết quả này không phải benchmark model chấm thi. Không đổi mặc định `run.py`.
Khi xong, **Runtime → Disconnect and delete runtime** để giải phóng tài nguyên.
""",
    )
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"name": "qwen_t4_dev.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def build() -> Path:
    base = Path(__file__).resolve().parents[1]
    output = base / "dist/table_qa_colab_dev.zip"
    output.parent.mkdir(exist_ok=True)
    nb_path = base / "notebooks/qwen_t4_dev.ipynb"
    nb_path.parent.mkdir(exist_ok=True)
    nb_path.write_text(json.dumps(notebook(), ensure_ascii=False, indent=2))
    files = [
        base / "run.py",
        base / "evaluate.py",
        base / "README.md",
        base / "pytest.ini",
        base / "requirements.txt",
        base / "requirements-dev.txt",
        base / "requirements-colab.txt",
        nb_path,
        *sorted((base / "src").glob("*.py")),
        *sorted((base / "benchmarks").glob("*.py")),
        *sorted((base / "tests").glob("*.py")),
    ]
    secrets = [
        value.encode()
        for name, value in dotenv_values(base / ".env").items()
        if value
        and any(term in name.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    ]
    with tempfile.TemporaryDirectory(prefix="tableqa-colab-") as temporary:
        root = Path(temporary)
        dataset_copy(base / "data", root / "colab_data/public", "sample_submission.csv")
        dataset_copy(
            base / "reports/optimization/frozen_holdout",
            root / "colab_data/holdout",
            "references.csv",
        )
        queries_path, answers_path = generate_fixtures(
            root / "synthetic", seed=20261015
        )
        queries = json.loads(queries_path.read_text())
        groups: dict[str, list[dict[str, Any]]] = {}
        for query in queries:
            groups.setdefault(query["family"], []).append(query)
        chosen: list[dict[str, Any]] = []
        while len(chosen) < 8:
            for family in sorted(groups):
                if groups[family] and len(chosen) < 8:
                    chosen.append(groups[family].pop(0))
        tuning = root / "colab_data/tuning"
        tuning.mkdir(parents=True)
        (tuning / "queries.json").write_text(
            json.dumps(chosen, ensure_ascii=False, indent=2)
        )
        shutil.copytree(root / "synthetic/xlsx_files", tuning / "xlsx_files")
        with answers_path.open() as stream:
            answers = {row["id"]: row["answer"] for row in csv.DictReader(stream)}
        with (tuning / "references.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["id", "answer"])
            writer.writeheader()
            writer.writerows(
                {"id": query["id"], "answer": answers[query["id"]]} for query in chosen
            )
        contents = {
            path.relative_to(base).as_posix(): path.read_bytes() for path in files
        }
        contents.update(
            {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in sorted((root / "colab_data").rglob("*"))
                if path.is_file()
            }
        )
        manifest = {
            "development_only": True,
            "contains_reference_answers_for_scoring_only": True,
            "files": {
                name: hashlib.sha256(body).hexdigest()
                for name, body in contents.items()
            },
        }
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for name, body in contents.items():
                if any(secret in body for secret in secrets):
                    raise ValueError("Credential in development bundle")
                archive.writestr(name, body)
            archive.writestr("bundle_manifest.json", json.dumps(manifest, indent=2))
    with ZipFile(output) as archive:
        if (
            archive.testzip()
            or sum(item.file_size for item in archive.infolist()) >= 100_000_000
        ):
            raise ValueError("Invalid or oversized development bundle")
    print(f"{output}: {output.stat().st_size} bytes")
    return output


if __name__ == "__main__":
    build()
