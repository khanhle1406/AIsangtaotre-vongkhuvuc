"""Validate the judge entrypoint in Docker using only an isolated mock API."""

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook

from src.llm_agent import DEFAULT_MODEL

MOCK_SERVER = """import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def reply(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.reply({"data": {"id": "qwen/qwen3.7-flash", "endpoints": [
            {"pricing": {"prompt": "0.0000002", "completion": "0.0000008"}}]}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if (self.path.startswith("/denied/")
            or self.headers.get("Authorization") != "Bearer smoke-placeholder"
            or body.get("model") != "qwen/qwen3.7-flash"):
            self.reply({"error": {"code": "unauthorized"}}, 401)
            return
        program = {"code": "result=num(sheets[0], 'B2')", "format": {"kind": "integer"}}
        self.reply({"model": "qwen/qwen3.7-flash", "choices": [
            {"message": {"content": json.dumps(program)}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 50, "cost": 0}})

HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
"""


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=90, check=True
    )


def smoke(image: str, destination: Path) -> dict[str, object]:
    """Mount inputs read-only, exercise success/failure and retain local evidence."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    input_root = destination / "input"
    files = input_root / "xlsx_files"
    files.mkdir(parents=True)
    output = destination / "output"
    output.mkdir()
    workbook = Workbook()
    workbook.active.append(["Item", "Units"])
    workbook.active.append(["Lamp", 47])
    workbook.save(files / "unseen.xlsx")
    workbook.close()
    queries = [
        {
            "id": key,
            "file_name": "unseen.xlsx",
            "query": "How many units? Answer only the integer.",
        }
        for key in ["câu-α", 42]
    ]
    (input_root / "queries.json").write_text(
        json.dumps(queries, ensure_ascii=False), encoding="utf-8"
    )
    originals = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in input_root.rglob("*")
        if path.is_file()
    }
    server_script = destination / "mock_api.py"
    server_script.write_text(MOCK_SERVER, encoding="utf-8")
    token = uuid4().hex[:12]
    network, server = f"submission-smoke-{token}", f"mock-{token}"
    config = json.loads(docker("image", "inspect", image).stdout)[0]
    assert (config["Os"], config["Architecture"]) == ("linux", "amd64")
    assert config["Config"]["Entrypoint"] == ["python", "run.py"]
    offline = docker(
        "run", "--rm", "--platform", "linux/amd64", "--network", "none", image, "--help"
    )
    assert "--xlsx-dir" in offline.stdout and "--openrouter-base-url" in offline.stdout
    docker("network", "create", "--internal", network)
    server_created = False
    runs: dict[str, object] = {}
    try:
        docker(
            "run",
            "--detach",
            "--platform",
            "linux/amd64",
            "--name",
            server,
            "--network",
            network,
            "--read-only",
            "--mount",
            f"type=bind,src={server_script},dst=/mock_api.py,readonly",
            "--entrypoint",
            "python",
            image,
            "/mock_api.py",
        )
        server_created = True
        docker(
            "exec",
            server,
            "python",
            "-c",
            "import socket,time\nfor i in range(50):\n try:\n  socket.create_connection(('127.0.0.1',8000),.2).close();break\n except OSError:\n  time.sleep(.1)\nelse:\n raise RuntimeError('Mock API did not start')",
        )
        for case, base, expected_exit in [
            ("success", "api", 0),
            ("unauthorized", "denied", 1),
        ]:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--platform",
                    "linux/amd64",
                    "--network",
                    network,
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,nosuid,size=64m",
                    "--memory",
                    "1g",
                    "--cpus",
                    "2",
                    "--mount",
                    f"type=bind,src={input_root},dst=/input,readonly",
                    "--mount",
                    f"type=bind,src={output},dst=/output",
                    image,
                    "--xlsx-dir",
                    "/input/xlsx_files",
                    "--queries",
                    "/input/queries.json",
                    "--output",
                    f"/output/{case}.csv",
                    "--openrouter-key",
                    "smoke-placeholder",
                    "--openrouter-model",
                    DEFAULT_MODEL,
                    "--openrouter-base-url",
                    f"http://{server}:8000/{base}/v1",
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            (destination / f"{case}.stdout.log").write_text(
                result.stdout, encoding="utf-8"
            )
            (destination / f"{case}.stderr.log").write_text(
                result.stderr, encoding="utf-8"
            )
            assert result.returncode == expected_exit, result.stderr
            assert "smoke-placeholder" not in result.stdout + result.stderr
            with (output / f"{case}.csv").open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                assert reader.fieldnames == ["id", "answer"]
                answers = list(reader)
            assert answers == [
                {"id": str(item["id"]), "answer": "47" if case == "success" else ""}
                for item in queries
            ]
            runs[case] = {"exit_code": result.returncode, "rows": len(answers)}
        assert {path.name for path in output.iterdir()} == {
            "success.csv",
            "unauthorized.csv",
        }
        assert originals == {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in input_root.rglob("*")
            if path.is_file()
        }
    finally:
        if server_created:
            docker("stop", "--time", "1", server)
            docker("rm", server)
        docker("network", "rm", network)
    report = {
        "image_id": config["Id"],
        "platform": "linux/amd64",
        "network": "internal mock only",
        "readonly_input": True,
        "input_hashes_unchanged": True,
        "runs": runs,
    }
    (destination / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="table-qa:submission-guide")
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(smoke(args.image, args.report_dir), indent=2))


if __name__ == "__main__":
    main()
