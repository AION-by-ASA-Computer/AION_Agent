from __future__ import annotations

import src.aion_env  # noqa: F401 — load .env before benchmark subprocess work

import argparse
import asyncio
import json
import sys
import traceback

from src.main import set_event_loop

from .general_agent import run_general_agent_benchmark
from .longmemeval_v2.runner import run_longmemeval_v2_small
from .long_document.runner import run_long_document_pipeline_eval
from .mnemos_bench.runner import run_mnemos_bench
from .registry import register_benchmark, BenchmarkSpec, catalog_entries
from .longmemeval_v2.prepare import is_dataset_ready
from .run_store import create_run, update_run_status


def _register_defaults() -> None:
    register_benchmark(
        BenchmarkSpec(
            id="general_agent",
            title="General agent eval",
            description="JSON case regression through AgentPipeline",
        ),
        _run_general_wrapper,
    )
    register_benchmark(
        BenchmarkSpec(
            id="longmemeval_v2_small",
            title="LongMemEval-V2 Small",
            description="LME-V2-Small long-term memory benchmark with Mnemos",
            tier="small",
            dataset_ready_fn=is_dataset_ready,
        ),
        _run_lme_wrapper,
    )
    register_benchmark(
        BenchmarkSpec(
            id="mnemos_bench",
            title="Mnemos recall micro-benchmark",
            description="Dev-only Mnemos FTS/hybrid recall validation",
        ),
        _run_mnemos_wrapper,
    )
    register_benchmark(
        BenchmarkSpec(
            id="long_document_pipeline",
            title="Long document pipeline eval",
            description="doc_ingest + grep golden cases (no LLM); see evals/long_document/cases/",
            tier="ci",
        ),
        _run_long_document_wrapper,
    )


async def _run_general_wrapper(
    run_id: str,
    profile_name: str,
    config: dict | None = None,
    dataset_path: str | None = None,
    **_: object,
) -> dict:
    if not dataset_path:
        raise ValueError("dataset_path required for general_agent")
    threshold = float((config or {}).get("threshold", 0.0))
    return await run_general_agent_benchmark(
        run_id=run_id,
        dataset_path=dataset_path,
        profile_name=profile_name,
        threshold=threshold,
        config=config,
    )


async def _run_lme_wrapper(
    run_id: str,
    profile_name: str,
    config: dict | None = None,
    **_: object,
) -> dict:
    return await run_longmemeval_v2_small(
        run_id=run_id,
        profile_name=profile_name,
        config=config,
    )


async def _run_mnemos_wrapper(
    run_id: str,
    profile_name: str,
    config: dict | None = None,
    dataset_path: str | None = None,
    **_: object,
) -> dict:
    if not dataset_path:
        dataset_path = "config_std/benchmarks/mnemos_recall.json"
    return await run_mnemos_bench(
        run_id=run_id,
        dataset_path=dataset_path,
        config=config,
    )


async def _run_long_document_wrapper(
    run_id: str,
    profile_name: str,
    config: dict | None = None,
    dataset_path: str | None = None,
    **_: object,
) -> dict:
    del run_id, profile_name, config  # pipeline eval is profile-agnostic
    if not dataset_path:
        dataset_path = "evals/long_document/cases/synthetic_smoke.yaml"
    return await run_long_document_pipeline_eval(dataset_path)


async def _async_main(args: argparse.Namespace) -> int:
    set_event_loop(asyncio.get_running_loop())
    _register_defaults()
    run_id = args.run_id
    if not run_id:
        from .job_manager import new_run_id

        run_id = new_run_id()
        print(f"[cli] run_id={run_id}", flush=True)
        await create_run(
            run_id,
            benchmark_id=args.benchmark,
            dataset_name=args.dataset or args.benchmark,
            profile_name=args.profile,
            config=json.loads(args.config_json) if args.config_json else {},
            status="running",
        )
    else:
        print(f"[cli] run_id={run_id} (provided)", flush=True)

    config = json.loads(args.config_json) if args.config_json else {}
    metrics: dict | None = None
    try:
        if args.benchmark == "general_agent":
            metrics = await run_general_agent_benchmark(
                run_id=run_id,
                dataset_path=args.dataset,
                profile_name=args.profile,
                threshold=float(config.get("threshold", 0.0)),
                config=config,
            )
        elif args.benchmark == "longmemeval_v2_small":
            metrics = await run_longmemeval_v2_small(
                run_id=run_id,
                profile_name=args.profile,
                config=config,
            )
        elif args.benchmark == "mnemos_bench":
            dataset = args.dataset or "config_std/benchmarks/mnemos_recall.json"
            metrics = await run_mnemos_bench(
                run_id=run_id,
                dataset_path=dataset,
                config=config,
            )
        elif args.benchmark == "long_document_pipeline":
            dataset = args.dataset or "evals/long_document/cases/synthetic_smoke.yaml"
            metrics = await run_long_document_pipeline_eval(dataset)
        else:
            raise ValueError(f"unknown benchmark: {args.benchmark}")
        if (
            metrics
            and args.benchmark == "mnemos_bench"
            and "accuracy_overall" in metrics
        ):
            acc = metrics["accuracy_overall"] * 100
            print(
                f"[cli] summary: {metrics.get('passed', 0)}/{metrics.get('case_count', 0)} "
                f"passed ({acc:.1f}%)",
                flush=True,
            )
        return 0
    except Exception as exc:
        await update_run_status(run_id, status="failed", error=str(exc))
        print(f"[cli] ERROR: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AION benchmark harness")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Execute a benchmark run")
    run_p.add_argument("--benchmark", required=True)
    run_p.add_argument("--run-id", default=None)
    run_p.add_argument("--profile", default="aion_std")
    run_p.add_argument("--dataset", default=None)
    run_p.add_argument("--config-json", default=None)

    prep_p = sub.add_parser("prepare-lme", help="Prepare LongMemEval-V2 dataset")
    prep_p.add_argument("--fixture", default=None)

    list_p = sub.add_parser("list", help="List available benchmarks")
    list_p.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args(argv)
    if args.command == "list":
        _register_defaults()
        entries = catalog_entries()
        if getattr(args, "json", False):
            print(json.dumps(entries, indent=2))
        else:
            print("Available benchmarks (CLI-only, dev validation):\n")
            for entry in entries:
                print(f"  {entry['id']}")
                print(f"    {entry.get('title', '')}")
                print(f"    {entry.get('description', '')}")
                if entry.get("tier"):
                    print(f"    tier: {entry['tier']}")
                print()
        return

    if args.command == "prepare-lme":
        from pathlib import Path

        from .longmemeval_v2.prepare import prepare_dataset

        fixture = Path(args.fixture) if args.fixture else None
        result = prepare_dataset(fixture=fixture)
        print(json.dumps(result, indent=2))
        return

    if args.command != "run":
        parser.print_help()
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    set_event_loop(loop)
    try:
        code = loop.run_until_complete(_async_main(args))
        sys.exit(code)
    except Exception:
        sys.exit(1)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
