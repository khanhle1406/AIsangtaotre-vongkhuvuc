"""Bounded Colab job used by both the notebook and the CLI (no credentials)."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .colab_io import atomic_json, export_results


def child_environment() -> dict[str, str]:
    return {
        **{
            key: value
            for key, value in os.environ.items()
            if not any(
                term in key.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD")
            )
        },
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONUNBUFFERED": "1",
    }


def terminate(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(session: Path, started: float, port: int = 8000) -> None:
    session.mkdir(parents=True, exist_ok=True)
    atomic_json(
        session / "job.json",
        {"status": "setup", "started": started, "hard_deadline": started + 2700},
    )
    environment = child_environment()
    server: subprocess.Popen[Any] | None = None
    runner: subprocess.Popen[Any] | None = None
    status: dict[str, Any] = {"started": started}
    try:
        remaining = started + 600 - time.time()
        if remaining <= 0:
            raise TimeoutError("Setup budget already expired")
        with (session / "install.log").open("w") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    "requirements-colab.txt",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
                check=True,
                timeout=remaining,
            )
        from .colab_local import local_json

        with (session / "server.log").open("w") as server_log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "benchmarks.colab_server",
                    "--session-dir",
                    str(session),
                    "--started",
                    str(started),
                    "--port",
                    str(port),
                ],
                stdout=server_log,
                stderr=subprocess.STDOUT,
                env=environment,
            )
        base = f"http://127.0.0.1:{port}/v1"
        while time.time() < started + 600:
            if server.poll() is not None:
                raise RuntimeError(
                    "Model server exited; inspect server_state.json/server.log"
                )
            try:
                metadata = local_json(base, "/models", timeout=2)["local"]
                if metadata["started"] != started:
                    raise RuntimeError("Port belongs to another local session")
                break
            except (OSError, TimeoutError):
                time.sleep(1)
        else:
            raise TimeoutError("Model setup exceeded ten minutes")
        with (session / "warmup.log").open("w") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "benchmarks.colab_runner",
                    "--warmup",
                    "--session-dir",
                    str(session),
                    "--base-url",
                    base,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                env=environment,
                timeout=max(1, started + 600 - time.time()),
            )
        atomic_json(
            session / "job.json",
            {
                "status": "benchmark",
                "started": started,
                "hard_deadline": started + 2700,
            },
        )
        with (session / "runner.log").open("w") as log:
            runner = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "benchmarks.colab_runner",
                    "--session-dir",
                    str(session),
                    "--base-url",
                    base,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
            )
        runner.wait(timeout=max(1, started + 2550 - time.time()))
        if runner.returncode:
            raise RuntimeError("Benchmark process failed; inspect runner.log")
        status["status"] = "completed"
    except (RuntimeError, OSError, TimeoutError, subprocess.SubprocessError) as error:
        status.update(status="incomplete", error=f"{type(error).__name__}: {error}")
    finally:
        if runner is not None:
            terminate(runner)
        if server is not None:
            terminate(server)
        status["elapsed_seconds"] = time.time() - started
        atomic_json(session / "job.json", status)
        export_results(session)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--started", type=float, required=True)
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    run(options.session_dir, options.started, options.port)
