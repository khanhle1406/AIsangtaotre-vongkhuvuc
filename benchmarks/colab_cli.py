"""Host-side Colab CLI operator; Google credentials never enter the GPU VM."""

import argparse
import hashlib
import json
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .colab_io import atomic_json


def drive_upload(
    path: Path, account: str, state_path: Path, quota_project: str | None = None
) -> dict[str, Any]:
    """Run inside the already-installed Colab CLI environment, with cached OAuth."""
    from colab_cli.auth import _get_google_auth_credentials
    from google.auth.transport.requests import AuthorizedSession

    credentials = _get_google_auth_credentials(
        str(Path.home() / ".colab-cli-oauth-config.json")
    )
    if quota_project:
        credentials = credentials.with_quota_project(quota_project)
    client = AuthorizedSession(credentials)
    identity = client.get("https://www.googleapis.com/oauth2/v2/userinfo", timeout=20)
    identity.raise_for_status()
    if identity.json().get("email") != account:
        raise ValueError("Drive account does not match the requested Colab account")
    state = json.loads(state_path.read_text()) if state_path.exists() else {"files": {}}
    if "folder_id" not in state:
        response = client.post(
            "https://www.googleapis.com/drive/v3/files",
            json={
                "name": "TableQA_T4_" + state_path.parent.name,
                "mimeType": "application/vnd.google-apps.folder",
            },
            timeout=30,
        )
        response.raise_for_status()
        state["folder_id"] = response.json()["id"]
        atomic_json(state_path, state)
    if path.name not in state["files"]:
        response = client.post(
            "https://www.googleapis.com/drive/v3/files",
            json={"name": path.name, "parents": [state["folder_id"]]},
            timeout=30,
        )
        response.raise_for_status()
        state["files"][path.name] = response.json()["id"]
        atomic_json(state_path, state)
    file_id = state["files"][path.name]
    with path.open("rb") as stream:
        response = client.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
            params={"uploadType": "media"},
            data=stream,
            headers={"Content-Type": "application/octet-stream"},
            timeout=45,
        )
    response.raise_for_status()
    state["last_synced_file"] = path.name
    state["last_synced_at"] = time.time()
    atomic_json(state_path, state)
    return {
        "folder_url": "https://drive.google.com/drive/folders/" + state["folder_id"]
    }


def operate(
    account: str,
    output: Path,
    archive: Path,
    local_checkpoints: bool = False,
    quota_project: str | None = None,
) -> None:
    if output.exists():
        raise ValueError("Use a new output directory; preserve previous evidence")
    output.mkdir(parents=True)
    binary = shutil.which("colab")
    if binary is None:
        raise RuntimeError("Colab CLI is not installed")
    cli_python = Path(binary).resolve().parent / "python"
    if not cli_python.exists():
        raise RuntimeError("Cannot locate the installed Colab CLI Python environment")
    config = str((output / "sessions.json").resolve())
    hard_deadline: float | None = None

    def cli(
        arguments: list[str], timeout: float = 60, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if hard_deadline is not None and arguments[0] != "stop":
            timeout = min(timeout, max(1, hard_deadline - time.time() - 60))
        return subprocess.run(
            [binary, "--auth", "oauth2", "--config", config, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    identity = cli(["whoami"]).stdout
    if not any(
        line.strip() == "Email:         " + account for line in identity.splitlines()
    ):
        # Avoid depending on column spacing in future CLI versions.
        email_lines = [
            line.split(":", 1)[1].strip()
            for line in identity.splitlines()
            if line.startswith("Email:")
        ]
        if email_lines != [account]:
            raise ValueError("Colab CLI account does not match requested identity")
    atomic_json(output / "account.json", {"email": account, "gpu_requested": "T4"})

    def sync(path: Path) -> None:
        if local_checkpoints:
            return
        arguments = [
            str(cli_python),
            "-m",
            "benchmarks.colab_cli",
            "--drive-upload",
            str(path.resolve()),
            "--account",
            account,
            "--drive-state",
            str((output / "drive.json").resolve()),
        ]
        if quota_project:
            arguments.extend(["--quota-project", quota_project])
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            check=False,
            capture_output=True,
            text=True,
            timeout=110
            if hard_deadline is None
            else min(110, max(1, hard_deadline - time.time() - 60)),
        )
        if result.returncode:
            (output / "drive_error.log").write_text(result.stderr)
            raise RuntimeError(
                "Drive synchronization failed; see the CLI/OAuth account permissions"
            )
        print(result.stdout.strip(), flush=True)

    # Validate Drive and save the exact source/data bundle before allocating GPU time.
    sync(archive)
    sync(Path("notebooks/qwen_t4_dev.ipynb"))
    atomic_json(
        output / "checkpoint_storage.json",
        {
            "local_mirror": True,
            "drive_enabled": not local_checkpoints,
            "quota_project": quota_project,
        },
    )
    name = "tableqa-t4-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    started = time.time()
    hard_deadline = started + 2700
    assigned = False
    last_hash = None
    remote_root = "/content/tableqa_t4"
    remote_results = "/content/tableqa_t4_results"
    status_script = output / "remote_status.py"
    status_script.write_text(
        "import json\nfrom pathlib import Path\np=Path(" + repr(remote_results) + ")\n"
        "j=json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {'status':'starting'}\n"
        "print('TABLEQA_STATUS:'+json.dumps({'job':j,'zip_ready':(p/'results.zip').exists()}))\n"
    )
    try:
        allocation = cli(["new", "-s", name, "--gpu", "T4"], timeout=120, check=False)
        (output / "allocation.log").write_text(allocation.stdout + allocation.stderr)
        if allocation.returncode:
            atomic_json(
                output / "status.json",
                {
                    "status": "allocation_failed",
                    "email": account,
                    "gpu": "T4",
                    "no_gpu_fallback": True,
                },
            )
            raise RuntimeError(
                "Colab did not allocate T4; inspect allocation.log. No alternative GPU was requested."
            )
        assigned = True
        atomic_json(
            output / "status.json",
            {"status": "allocated", "session": name, "started": started},
        )
        cli(
            [
                "upload",
                "-s",
                name,
                str(archive.resolve()),
                "/content/table_qa_colab_dev.zip",
            ]
        )
        launch = output / "remote_launch.py"
        launch.write_text(
            "import hashlib,json,os,stat,subprocess,sys,zipfile\nfrom pathlib import Path\n"
            f"work=Path({remote_root!r}); work.mkdir(exist_ok=False)\n"
            "with zipfile.ZipFile('/content/table_qa_colab_dev.zip') as z:\n"
            " if sum(i.file_size for i in z.infolist())>100_000_000: raise ValueError('Bundle too large')\n"
            " manifest=json.loads(z.read('bundle_manifest.json'))\n"
            " for item in z.infolist():\n"
            "  if not (work/item.filename).resolve().is_relative_to(work.resolve()) or stat.S_ISLNK(item.external_attr>>16): raise ValueError('Unsafe archive')\n"
            "  if item.filename!='bundle_manifest.json' and hashlib.sha256(z.read(item)).hexdigest()!=manifest['files'].get(item.filename): raise ValueError('Bundle hash mismatch')\n"
            " z.extractall(work)\n"
            f"root=Path({remote_results!r}); root.mkdir(exist_ok=False)\n"
            f"args=[sys.executable,'-m','benchmarks.colab_bootstrap','--session-dir',str(root),'--started',{str(started)!r}]\n"
            "with (root/'bootstrap.log').open('w') as log:\n"
            " job=subprocess.Popen(args,cwd=work,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)\n"
            "print('TABLEQA_JOB_PID',job.pid)\n"
        )
        cli(
            ["exec", "-s", name, "-f", str(launch.resolve()), "--timeout", "45"],
            timeout=60,
        )
        while time.time() < started + 2640:
            result = cli(
                [
                    "exec",
                    "-s",
                    name,
                    "-f",
                    str(status_script.resolve()),
                    "--timeout",
                    "20",
                ],
                timeout=35,
            )
            lines = [
                line.split("TABLEQA_STATUS:", 1)[1]
                for line in result.stdout.splitlines()
                if "TABLEQA_STATUS:" in line
            ]
            if not lines:
                raise RuntimeError("Missing remote job status")
            status = json.loads(lines[-1])
            atomic_json(output / "remote_job.json", status)
            if status["zip_ready"]:
                cli(
                    [
                        "download",
                        "-s",
                        name,
                        remote_results + "/results.zip",
                        str((output / "results.zip").resolve()),
                    ]
                )
                digest = hashlib.sha256(
                    (output / "results.zip").read_bytes()
                ).hexdigest()
                if digest != last_hash:
                    sync(output / "results.zip")
                    last_hash = digest
            print(
                json.dumps(
                    {"elapsed_seconds": round(time.time() - started), **status["job"]}
                ),
                flush=True,
            )
            if status["job"]["status"] in {"completed", "incomplete"}:
                atomic_json(output / "status.json", {"session": name, **status["job"]})
                break
            time.sleep(10)
        else:
            atomic_json(
                output / "status.json", {"status": "45_minute_limit", "session": name}
            )
    finally:
        if assigned:
            stopped = cli(["stop", "-s", name], timeout=60, check=False)
            (output / "release.log").write_text(stopped.stdout + stopped.stderr)
            if stopped.returncode:
                raise RuntimeError("Runtime release failed; inspect release.log")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--archive", type=Path, default=Path("dist/table_qa_colab_dev.zip")
    )
    parser.add_argument("--drive-upload", type=Path)
    parser.add_argument("--drive-state", type=Path)
    parser.add_argument("--quota-project")
    parser.add_argument(
        "--local-checkpoints",
        action="store_true",
        help="Explicit recovery when Drive API is unavailable; do not claim Drive persistence",
    )
    args = parser.parse_args()
    if args.drive_upload:
        if args.drive_state is None:
            parser.error("--drive-state is required")
        print(
            json.dumps(
                drive_upload(
                    args.drive_upload,
                    args.account,
                    args.drive_state,
                    args.quota_project,
                )
            )
        )
    else:
        if args.output is None:
            parser.error("--output is required")

        def interrupted(_signal: int, _frame: Any) -> None:
            raise KeyboardInterrupt("Colab operator interrupted")

        signal.signal(signal.SIGTERM, interrupted)
        operate(
            args.account,
            args.output,
            args.archive,
            args.local_checkpoints,
            args.quota_project,
        )


if __name__ == "__main__":
    main()
