"""One reproducible live experiment, charged to the persistent development budget."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import run_queries, validate_queries
from src import llm_agent
from src.llm_agent import LLMAgent

from .budget import workspace_budget
from .compare import score, source_hash
from .providers import provider_transport


def experiment(
    root: Path,
    input_dir: Path,
    queries_path: Path,
    references_path: Path,
    limit: float = 0.03,
    concurrency: int = 2,
    reasoning: int = 256,
    max_tokens: int = 2048,
    compact_prompt: bool = False,
    adaptive_reasoning: bool = False,
    provider: str = "openrouter",
    baseline: bool = False,
    development_model: str | None = None,
    local_base_url: str = "http://127.0.0.1:8000/v1",
    deadline_seconds: float = 600,
    helper_contract: bool = False,
    gateway_batch: Path | None = None,
    thinking: str | None = "low",
) -> dict[str, Any]:
    if root.exists():
        raise ValueError("Experiment directory already exists")
    queries = validate_queries(queries_path, input_dir)
    references = read_answers(references_path)
    ids = {str(item["id"]) for item in queries}
    if not ids or not ids <= references.keys():
        raise ValueError("Reference IDs do not cover experiment queries")
    budget = workspace_budget()
    if not 1 <= deadline_seconds <= 2700:
        raise ValueError("Invalid development deadline")
    if provider == "colab-local" and (concurrency != 1 or adaptive_reasoning):
        raise ValueError("Colab local requires concurrency 1 and non-thinking decoding")
    if baseline and (provider in {"openrouter-free", "colab-local"} or helper_contract):
        raise ValueError("Free development model is not a Qwen baseline")
    if baseline and (compact_prompt or adaptive_reasoning or concurrency > 2):
        raise ValueError("Baseline uses its original configuration")
    if baseline:
        from .offline import baseline_modules

        _, _, module, parser = baseline_modules(
            Path("reports/optimization/baseline_source")
        )
    else:
        module, parser = llm_agent, None
    root.mkdir(parents=True)
    provenance = {
        "source_sha256": source_hash(),
        "queries_sha256": hashlib.sha256(queries_path.read_bytes()).hexdigest(),
        "workbooks": {
            name: hashlib.sha256((input_dir / name).read_bytes()).hexdigest()
            for name in sorted({item["file_name"] for item in queries})
        },
        "concurrency": concurrency,
        "reasoning_tokens": reasoning,
        "max_tokens": max_tokens,
        "compact_prompt": compact_prompt,
        "adaptive_reasoning": adaptive_reasoning,
        "provider": provider,
        "development_model": development_model,
        "helper_contract": helper_contract,
        "judge_model_benchmark": provider == "openrouter",
        "baseline_snapshot": baseline,
    }
    (root / "provenance.json").write_text(json.dumps(provenance, indent=2))
    output = root / "submission.csv"
    with (
        budget.stage(str(root.resolve()), limit) as ledger,
        provider_transport(
            provider, module, development_model, local_base_url
        ) as transport,
    ):
        arguments = {
            "api_key": transport["api_key"],
            "pricing": transport["pricing"],
            "ledger": ledger,
            "reasoning_tokens": reasoning,
            "max_tokens": max_tokens,
            "deadline": time.monotonic() + deadline_seconds,
        }
        if baseline:
            original = module.LLMAgent(**arguments)
            client = BaselineAdapter(original, parser)
            provenance["baseline_source_sha256"] = json.loads(
                Path("reports/optimization/baseline_source/manifest.json").read_text()
            )["source_sha256"]
        else:
            client_class = transport.get("client_class", LLMAgent)
            if provider == "gateway":
                from .gateway import BatchLimits

                if helper_contract:
                    from .gateway_runner import PromptedGatewayAgent

                    client_class = PromptedGatewayAgent

                transport["client_kwargs"].update(
                    batch_limits=BatchLimits(gateway_batch or root / "batch.json"),
                    thinking=thinking,
                )
            client = client_class(
                **arguments,
                **transport.get("client_kwargs", {}),
                compact_prompt=compact_prompt,
                adaptive_reasoning=adaptive_reasoning,
                worker_memory_mb=128 if concurrency == 4 else 256,
            )
        provenance["base_url"] = transport["base_url"]
        provenance["pricing_upper_per_token"] = transport["pricing"]
        provenance["model"] = client.model
        if helper_contract:
            from .gateway_runner import HELPER_CONTRACT

            client.system_prompt += HELPER_CONTRACT
            if provider == "gateway":
                client.helper_instructions = HELPER_CONTRACT
        provenance["reasoning_tokens"] = client.reasoning_tokens
        if provider == "gateway":
            provenance.update(
                thinking=thinking or "unknown",
                temperature=1.0,
                cost_basis="free according to user; provider cost recorded separately",
            )
        if provider == "colab-local":
            provenance["local"] = client.local_metadata
        if "free_quota" in transport:
            provenance["free_quota_before"] = transport["free_quota"]
        (root / "provenance.json").write_text(json.dumps(provenance, indent=2))
        metrics = run_queries(input_dir, queries, output, client, concurrency)
    report = {
        "score": score(output, references, ids),
        "metrics": metrics,
        "fatal_error": client.fatal_error,
        "development_cost_upper_usd": 0.5 - budget.remaining,
        **provenance,
    }
    (root / "report.json").write_text(json.dumps(report, indent=2))
    return report


class BaselineAdapter:
    """Use snapshot prompt/wire/solver with the same input values and scheduler."""

    compact_prompt = False
    adaptive_reasoning = False
    worker_memory_mb = 256

    def __init__(self, client: Any, parser: Any) -> None:
        self.client, self.parser = client, parser

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def solve_workbook(self, workbook: Any, query: str, max_retries: int = 2) -> Any:
        legacy = self.parser.WorkbookData(workbook.sheets, workbook.estimated_bytes)
        return self.client.solve_workbook(legacy, query, max_retries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, default=Path("data/xlsx_files"))
    parser.add_argument("--queries", type=Path, default=Path("data/queries.json"))
    parser.add_argument(
        "--references", type=Path, default=Path("data/sample_submission.csv")
    )
    parser.add_argument("--limit", type=float, default=0.03)
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4], default=2)
    parser.add_argument("--reasoning", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--compact-prompt", action="store_true")
    parser.add_argument("--adaptive-reasoning", action="store_true")
    parser.add_argument(
        "--provider",
        choices=[
            "openrouter",
            "bazaarlink",
            "openrouter-free",
            "colab-local",
            "gateway",
        ],
        default="openrouter",
    )
    parser.add_argument(
        "--development-model", help="Pinned :free model for development"
    )
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--local-base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--deadline-seconds", type=float, default=600)
    parser.add_argument("--helper-contract", action="store_true")
    parser.add_argument("--gateway-batch", type=Path)
    parser.add_argument(
        "--thinking", choices=["low", "minimal", "unknown"], default="low"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            experiment(
                args.report_dir,
                args.input_dir,
                args.queries,
                args.references,
                args.limit,
                args.concurrency,
                args.reasoning,
                args.max_tokens,
                args.compact_prompt,
                args.adaptive_reasoning,
                args.provider,
                args.baseline,
                args.development_model,
                args.local_base_url,
                args.deadline_seconds,
                args.helper_contract,
                args.gateway_batch,
                None if args.thinking == "unknown" else args.thinking,
            ),
            indent=2,
        )
    )
