"""Notebook-owned, loopback-only T4 model server. GPU dependencies are optional."""

import argparse
import gc
import importlib.metadata
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import psutil

from .colab_io import atomic_json
from .colab_local import LOCAL_MODEL, LOCAL_REVISION


class SessionControl:
    """Persistent session-wide deadline and generation quota, including warm-up."""

    def __init__(self, root: Path, started: float) -> None:
        self.root, self.started = root, started
        self.inference_deadline = started + 42 * 60
        self.setup_deadline = started + 10 * 60
        self.generations = 0
        self.context_length = 24576
        self.oom_fallback_used = False
        self.fatal_error: str | None = None
        self.ready = False
        self.history: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        state_path = root / "server_state.json"
        if state_path.exists():
            saved = json.loads(state_path.read_text())
            if saved["started"] != started:
                raise ValueError("Session directory belongs to another session")
            self.generations = saved["generations"]
            self.context_length = saved["context_length"]
            self.oom_fallback_used = saved["oom_fallback_used"]
            self.fatal_error = saved["fatal_error"]
            self.history = saved["history"]

    def reserve(self, warmup: bool = False) -> None:
        if self.fatal_error:
            raise RuntimeError(self.fatal_error)
        deadline = self.setup_deadline if warmup else self.inference_deadline
        if time.time() >= deadline or self.generations >= 100:
            raise TimeoutError("Session deadline or 100-generation limit reached")
        self.generations += 1
        self.save()

    def oom(self, warmup: bool) -> bool:
        if warmup and not self.oom_fallback_used:
            self.oom_fallback_used = True
            self.context_length = 16384
            self.save()
            return True
        self.fatal_error = "CUDA OOM; no further generations permitted"
        self.save()
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "model": LOCAL_MODEL,
            "revision": LOCAL_REVISION,
            "context_length": self.context_length,
            "quantization": "NF4 double-quant",
            "compute_dtype": "float16",
            "kv_dtype": "float16",
            "attention": "sdpa",
            "thinking": False,
            "started": self.started,
            "inference_deadline": self.inference_deadline,
            "hard_deadline": self.started + 2700,
            "generations": self.generations,
            "generation_limit": 100,
            "oom_fallback_used": self.oom_fallback_used,
            "fatal_error": self.fatal_error,
            "ready": self.ready,
            "history": self.history,
            "server_rss_bytes": psutil.Process().memory_info().rss,
        }

    def save(self) -> None:
        atomic_json(self.root / "server_state.json", self.snapshot())


class T4Engine:
    def __init__(self, control: SessionControl) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; CPU fallback is disabled")
        properties = torch.cuda.get_device_properties(0)
        if "T4" not in properties.name or properties.total_memory < 14 * 1024**3:
            raise RuntimeError("This notebook requires a T4 with at least 14 GiB VRAM")
        self.torch, self.control = torch, control
        self.device_info = {
            "gpu": properties.name,
            "vram_total_bytes": properties.total_memory,
            "ram_total_bytes": psutil.virtual_memory().total,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            **{
                package: importlib.metadata.version(package)
                for package in ("transformers", "accelerate", "bitsandbytes")
            },
        }
        self.tokenizer = AutoTokenizer.from_pretrained(
            LOCAL_MODEL, revision=LOCAL_REVISION, trust_remote_code=False
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            LOCAL_MODEL,
            revision=LOCAL_REVISION,
            trust_remote_code=False,
            torch_dtype=torch.float16,
            attn_implementation="sdpa",
            device_map={"": 0},
            low_cpu_mem_usage=True,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            ),
        ).eval()
        if time.time() >= control.setup_deadline:
            raise TimeoutError("Model setup exceeded ten minutes")
        control.ready = True
        control.save()
        atomic_json(control.root / "hardware.json", self.device_info)

    def token_ids(self, messages: Any) -> list[int]:
        if (
            not isinstance(messages, list)
            or not messages
            or any(
                not isinstance(message, dict)
                or message.get("role") not in {"system", "user", "assistant"}
                or not isinstance(message.get("content"), str)
                for message in messages
            )
        ):
            raise ValueError("Expected text chat messages")
        return self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True
        )

    def generate(self, body: dict[str, Any], warmup: bool = False) -> dict[str, Any]:
        from transformers import StoppingCriteria, StoppingCriteriaList

        maximum = body.get("max_tokens", 2048)
        if (
            body.get("model") != LOCAL_MODEL
            or type(maximum) is not int
            or not 1 <= maximum <= 2048
            or "reasoning" in body
            or body.get("temperature", 0) != 0
        ):
            raise ValueError("Unsupported local generation parameters")
        ids = self.token_ids(body.get("messages"))
        if len(ids) + maximum > self.control.context_length:
            raise ValueError("Context overflow; no input was truncated")
        self.control.reserve(warmup)
        started = time.time()
        deadline = min(
            started + min(115, max(1, float(body.get("timeout_seconds", 115)))),
            self.control.setup_deadline if warmup else self.control.inference_deadline,
        )

        class DeadlineStop(StoppingCriteria):
            def __call__(self, *_args: Any, **_kwargs: Any) -> bool:
                return time.time() >= deadline

        record: dict[str, Any] = {
            "generation": self.control.generations,
            "warmup": warmup,
            "prompt_tokens": len(ids),
        }
        try:
            self.torch.cuda.reset_peak_memory_stats()
            inputs = self.torch.tensor([ids], device="cuda:0")
            with self.torch.inference_mode():
                output = self.model.generate(
                    input_ids=inputs,
                    attention_mask=self.torch.ones_like(inputs),
                    do_sample=False,
                    max_new_tokens=maximum,
                    use_cache=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    stopping_criteria=StoppingCriteriaList([DeadlineStop()]),
                )
            generated = output[0, len(ids) :].tolist()
            timed_out = time.time() >= deadline
            record.update(
                elapsed_seconds=time.time() - started,
                completion_tokens=len(generated),
                timed_out=timed_out,
                peak_vram_allocated_bytes=self.torch.cuda.max_memory_allocated(),
                peak_vram_reserved_bytes=self.torch.cuda.max_memory_reserved(),
            )
            if timed_out:
                raise TimeoutError("Generation reached its local deadline")
            return {
                "model": LOCAL_MODEL,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": self.tokenizer.decode(
                                generated, skip_special_tokens=True
                            ),
                        },
                        "finish_reason": "stop"
                        if generated and generated[-1] == self.tokenizer.eos_token_id
                        else "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": len(ids),
                    "completion_tokens": len(generated),
                    "total_tokens": len(ids) + len(generated),
                    "cost": 0,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
                "local": {"billing": "local compute; no paid inference API", **record},
            }
        except self.torch.cuda.OutOfMemoryError:
            record["error"] = "CUDA OOM"
            self.control.oom(warmup)
            gc.collect()
            self.torch.cuda.empty_cache()
            raise
        finally:
            record.setdefault("elapsed_seconds", time.time() - started)
            self.control.history.append(record)
            self.control.save()


def handler_for(engine: Any, control: SessionControl) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            print(format % args, flush=True)

        def reply(self, status: int, data: dict[str, Any]) -> None:
            encoded = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def do_GET(self) -> None:
            if self.path != "/v1/models":
                self.reply(404, {"error": {"code": "unknown_endpoint"}})
                return
            self.reply(
                200,
                {"data": [{"id": LOCAL_MODEL}], "local": control.snapshot()},
            )

        def do_POST(self) -> None:
            if self.path not in {"/v1/tokenize", "/v1/chat/completions", "/v1/warmup"}:
                self.reply(404, {"error": {"code": "unknown_endpoint"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4 * 1024**2:
                    raise ValueError("Request body missing or too large")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise TypeError("Expected JSON object")
                if self.path == "/v1/tokenize":
                    self.reply(
                        200, {"tokens": len(engine.token_ids(body.get("messages")))}
                    )
                    return
                with control.lock:
                    result = engine.generate(body, warmup=self.path == "/v1/warmup")
                self.reply(200, result)
            except (ValueError, json.JSONDecodeError, TypeError) as error:
                self.reply(
                    400, {"error": {"code": "invalid_request", "message": str(error)}}
                )
            except TimeoutError as error:
                self.reply(
                    408, {"error": {"code": "local_deadline", "message": str(error)}}
                )
            except RuntimeError as error:
                # Runtime errors are terminal unless the one warm-up OOM fallback is pending.
                fallback = (
                    self.path == "/v1/warmup"
                    and control.oom_fallback_used
                    and not control.fatal_error
                )
                if not fallback:
                    control.fatal_error = type(error).__name__
                    control.save()
                self.reply(
                    507,
                    {
                        "error": {"code": "local_runtime_failure"},
                        "local": control.snapshot(),
                    },
                )

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--started", type=float, required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    control = SessionControl(args.session_dir, args.started)
    control.save()
    try:
        engine = T4Engine(control)
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), handler_for(engine, control)
        )
        server.daemon_threads = True
        server.serve_forever()
    except (RuntimeError, ValueError, ImportError, OSError, TimeoutError) as error:
        control.fatal_error = f"{type(error).__name__}: {error}"
        control.save()
        raise


if __name__ == "__main__":
    main()
