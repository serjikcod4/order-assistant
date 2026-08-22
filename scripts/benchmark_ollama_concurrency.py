"""Run a bounded, synthetic shadow-only API benchmark."""

import argparse
import json
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


SYNTHETIC_REQUEST = (
    "Нужно 500 подшипников SKF 6204 до 250 грн за штуку. "
    "Если SKF нет, можно FAG. Доставка 2026-08-17 09:00."
)
ADMIN_HEADERS = {
    "X-Demo-Actor-Id": "benchmark-admin",
    "X-Demo-Actor-Role": "admin",
}


def require_shadow(readiness_payload: dict[str, object]) -> None:
    details = readiness_payload.get("details", {})
    mode = details.get("rollout_mode") if isinstance(details, dict) else None
    if mode != "shadow":
        raise RuntimeError(
            f"Benchmark requires shadow rollout mode; current mode is {mode!r}."
        )


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 2)


def run_benchmark(
    *,
    requests: int,
    concurrency: int,
    base_url: str,
    timeout: float,
) -> dict[str, object]:
    if requests <= 0 or concurrency <= 0 or timeout <= 0:
        raise ValueError("requests, concurrency and timeout must be positive.")
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        ready = client.get(f"{base_url}/health/ready")
        ready.raise_for_status()
        require_shadow(ready.json())

    def one_request(index: int) -> dict[str, object]:
        started = time.perf_counter()
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{base_url}/api/v1/order-requests/from-text",
                json={"text": SYNTHETIC_REQUEST},
                headers={"X-Request-ID": _request_id(index)},
            )
            latency_ms = (time.perf_counter() - started) * 1000
            payload = response.json()
            if response.status_code != 200:
                return {
                    "success": False,
                    "latency_ms": latency_ms,
                    "error_code": payload.get("error", {}).get(
                        "code", "unknown_error"
                    ),
                }
            if payload.get("status") != "shadow_processed" or payload.get(
                "draft_id"
            ) is not None:
                return {
                    "success": False,
                    "latency_ms": latency_ms,
                    "error_code": "unsafe_non_shadow_response",
                    "draft_created": payload.get("draft_id") is not None,
                }
            audit_id = payload["audit_id"]
            audit_response = client.get(
                f"{base_url}/api/v1/extraction-audits/{audit_id}",
                headers=ADMIN_HEADERS,
            )
            audit_response.raise_for_status()
            audit = audit_response.json()["audit"]
            return {
                "success": True,
                "latency_ms": latency_ms,
                "queue_wait_ms": audit["queue_wait_ms"],
                "inference_ms": audit["inference_ms"],
                "draft_created": False,
            }

    benchmark_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(one_request, range(requests)))
    elapsed = time.perf_counter() - benchmark_started
    successes = [result for result in results if result["success"]]
    failures = [result for result in results if not result["success"]]
    latencies = [float(result["latency_ms"]) for result in results]
    queue_wait = [float(result["queue_wait_ms"]) for result in successes]
    inference = [float(result["inference_ms"]) for result in successes]
    errors_by_code = Counter(str(result["error_code"]) for result in failures)
    return {
        "configuration": {
            "requests": requests,
            "concurrency": concurrency,
            "base_url": base_url,
            "timeout_seconds": timeout,
            "rollout_mode": "shadow",
        },
        "success_count": len(successes),
        "failure_count": len(failures),
        "throughput_requests_per_second": round(requests / elapsed, 3),
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "queue_wait_ms_p50": percentile(queue_wait, 0.50),
        "queue_wait_ms_p95": percentile(queue_wait, 0.95),
        "inference_ms_p50": percentile(inference, 0.50),
        "inference_ms_p95": percentile(inference, 0.95),
        "capacity_rejected_count": errors_by_code["llm_capacity_exceeded"],
        "queue_timeout_count": errors_by_code["llm_queue_timeout"],
        "circuit_open_rejected_count": errors_by_code["llm_circuit_open"],
        "draft_created_count": sum(
            bool(result.get("draft_created")) for result in results
        ),
        "errors_by_code": dict(errors_by_code),
    }


def _request_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def write_reports(report: dict[str, object], output: Path) -> tuple[Path, Path]:
    json_path = output if output.suffix == ".json" else output.with_suffix(".json")
    markdown_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _markdown(report: dict[str, object]) -> str:
    configuration = report["configuration"]
    return (
        "# Ollama shadow concurrency benchmark\n\n"
        f"- Requests: {configuration['requests']}\n"
        f"- Concurrency: {configuration['concurrency']}\n"
        f"- Successes: {report['success_count']}\n"
        f"- Failures: {report['failure_count']}\n"
        f"- Throughput: {report['throughput_requests_per_second']} req/s\n"
        f"- Latency p50/p95: {report['latency_ms_p50']} / "
        f"{report['latency_ms_p95']} ms\n"
        f"- Queue wait p50/p95: {report['queue_wait_ms_p50']} / "
        f"{report['queue_wait_ms_p95']} ms\n"
        f"- Errors: `{json.dumps(report['errors_by_code'])}`\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_benchmark(
        requests=args.requests,
        concurrency=args.concurrency,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    json_path, markdown_path = write_reports(report, args.output)
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")


if __name__ == "__main__":
    main()
