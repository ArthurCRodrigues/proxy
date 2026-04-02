#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import select
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunResult:
    run: int
    seconds: float


class ACPClient:
    def __init__(self, proc: subprocess.Popen[str], allow_all: bool) -> None:
        self.proc = proc
        self.allow_all = allow_all
        self.next_id = 1
        self.protocol_version = 1

    @classmethod
    def start(
        cls,
        command: str,
        model: str,
        allow_all: bool,
        cwd: Path,
        timeout_seconds: float,
    ) -> ACPClient:
        cmd = [command, "--acp", "--stdio"]
        if allow_all:
            cmd.append("--allow-all")
        if model:
            cmd.extend(["--model", model])
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        client = cls(proc=proc, allow_all=allow_all)
        init_result, _ = client._request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "copilot-latency-benchmark", "version": "1.0.0"},
            },
            timeout_seconds=timeout_seconds,
            measure_elapsed=False,
        )
        client.protocol_version = int(init_result.get("protocolVersion", 1))
        return client

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2.0)

    def new_session(self, timeout_seconds: float, cwd: Path) -> str:
        result, _ = self._request(
            "session/new",
            {"cwd": str(cwd), "mcpServers": []},
            timeout_seconds=timeout_seconds,
            measure_elapsed=False,
        )
        session_id = str(result.get("sessionId", "")).strip()
        if not session_id:
            raise RuntimeError("ACP session/new did not return sessionId")
        return session_id

    def prompt(self, session_id: str, prompt: str, timeout_seconds: float) -> tuple[float, dict[str, Any]]:
        result, elapsed = self._request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
            timeout_seconds=timeout_seconds,
            measure_elapsed=True,
        )
        assert elapsed is not None
        return elapsed, result

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        timeout_seconds: float,
        measure_elapsed: bool,
    ) -> tuple[dict[str, Any], float | None]:
        req_id = self.next_id
        self.next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        started = time.perf_counter() if measure_elapsed else None
        self._send_json(payload)

        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for ACP response to {method}")
            message = self._read_message(remaining)
            if "id" in message and ("result" in message or "error" in message):
                message_id = message.get("id")
                if message_id == req_id:
                    if "error" in message:
                        raise RuntimeError(f"ACP error for {method}: {message['error']}")
                    result = message.get("result")
                    if not isinstance(result, dict):
                        result = {}
                    elapsed = time.perf_counter() - started if started is not None else None
                    return result, elapsed
                continue

            incoming_method = str(message.get("method", ""))
            if incoming_method == "session/request_permission":
                permission_id = message.get("id")
                if isinstance(permission_id, int):
                    outcome = "allow" if self.allow_all else "cancelled"
                    self._send_json(
                        {
                            "jsonrpc": "2.0",
                            "id": permission_id,
                            "result": {"outcome": {"outcome": outcome}},
                        }
                    )

    def _send_json(self, payload: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise RuntimeError("ACP stdin is unavailable")
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def _read_message(self, timeout_seconds: float) -> dict[str, Any]:
        if self.proc.stdout is None:
            raise RuntimeError("ACP stdout is unavailable")

        if self.proc.poll() is not None:
            err = ""
            if self.proc.stderr is not None:
                err = self.proc.stderr.read().strip()
            raise RuntimeError(f"ACP process exited unexpectedly ({self.proc.returncode}): {err}")

        ready, _, _ = select.select([self.proc.stdout], [], [], timeout_seconds)
        if not ready:
            raise TimeoutError("Timed out waiting for ACP message")

        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("ACP stdout closed unexpectedly")

        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ACP emitted invalid JSON: {line!r}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"ACP emitted non-object JSON: {parsed!r}")
        return parsed


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[idx]


def _summary(results: list[RunResult]) -> dict[str, float]:
    values = [r.seconds for r in results]
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": _p95(values),
    }


def benchmark_classic(
    command: str,
    model: str,
    allow_all: bool,
    prompt: str,
    runs: int,
    cwd: Path,
    timeout_seconds: float,
) -> list[RunResult]:
    cmd = [command, "--output-format", "json", "-p", prompt]
    if allow_all:
        cmd.append("--allow-all")
    if model:
        cmd.extend(["--model", model])

    results: list[RunResult] = []
    for i in range(1, runs + 1):
        started = time.perf_counter()
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = time.perf_counter() - started
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                f"Classic run {i} failed with exit code {completed.returncode}: {stderr}"
            )
        results.append(RunResult(run=i, seconds=elapsed))
    return results


def benchmark_acp(
    command: str,
    model: str,
    allow_all: bool,
    prompt: str,
    runs: int,
    cwd: Path,
    timeout_seconds: float,
    fresh_session_per_run: bool,
) -> list[RunResult]:
    client = ACPClient.start(
        command=command,
        model=model,
        allow_all=allow_all,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )
    try:
        shared_session_id = ""
        if not fresh_session_per_run:
            shared_session_id = client.new_session(timeout_seconds=timeout_seconds, cwd=cwd)

        results: list[RunResult] = []
        for i in range(1, runs + 1):
            session_id = shared_session_id
            if fresh_session_per_run:
                session_id = client.new_session(timeout_seconds=timeout_seconds, cwd=cwd)
            elapsed, result = client.prompt(
                session_id=session_id,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
            stop_reason = str(result.get("stopReason", "end_turn")).strip().lower()
            if stop_reason and stop_reason != "end_turn":
                raise RuntimeError(f"ACP run {i} returned stopReason={stop_reason}")
            results.append(RunResult(run=i, seconds=elapsed))
        return results
    finally:
        client.close()


def _print_report(
    classic_results: list[RunResult],
    acp_results: list[RunResult],
    prompt: str,
    fresh_session_per_run: bool,
) -> None:
    classic = _summary(classic_results)
    acp = _summary(acp_results)
    diff_mean = classic["mean"] - acp["mean"]
    speedup = classic["mean"] / acp["mean"] if acp["mean"] > 0 else float("inf")

    print("\nCopilot latency benchmark")
    print(f"Prompt: {prompt!r}")
    print(f"ACP mode: {'fresh session per run' if fresh_session_per_run else 'single warm session'}")
    print("\nPer-run latency (seconds):")
    print("run\tclassic\tacp")
    for classic_row, acp_row in zip(classic_results, acp_results, strict=True):
        print(f"{classic_row.run}\t{classic_row.seconds:.3f}\t{acp_row.seconds:.3f}")

    print("\nSummary (seconds):")
    print("method\tmin\tmedian\tmean\tp95\tmax")
    print(
        "classic\t"
        f"{classic['min']:.3f}\t{classic['median']:.3f}\t{classic['mean']:.3f}\t"
        f"{classic['p95']:.3f}\t{classic['max']:.3f}"
    )
    print(
        "acp\t"
        f"{acp['min']:.3f}\t{acp['median']:.3f}\t{acp['mean']:.3f}\t"
        f"{acp['p95']:.3f}\t{acp['max']:.3f}"
    )
    print(
        "\nMean improvement: "
        f"{diff_mean:.3f}s faster with ACP ({speedup:.2f}x speedup)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark classic copilot -p latency vs warm ACP prompt latency."
    )
    parser.add_argument(
        "--prompt",
        default="Reply with exactly one short sentence: ready.",
        help="Prompt text to send to Copilot for each run.",
    )
    parser.add_argument("--runs", type=int, default=5, help="Number of runs per method.")
    parser.add_argument("--command", default="copilot", help="Copilot executable name/path.")
    parser.add_argument("--model", default="", help="Optional Copilot model name.")
    parser.add_argument(
        "--cwd",
        default=".",
        help="Working directory used for Copilot invocations.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="Timeout per request/run.",
    )
    parser.add_argument(
        "--no-allow-all",
        action="store_true",
        help="Do not pass --allow-all to Copilot commands.",
    )
    parser.add_argument(
        "--fresh-acp-session-per-run",
        action="store_true",
        help="Create a new ACP session for each timed run (still keeps one warm ACP process).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON report instead of table text.",
    )
    args = parser.parse_args()

    if args.runs <= 0:
        raise ValueError("--runs must be >= 1")

    cwd = Path(args.cwd).expanduser().resolve()
    allow_all = not args.no_allow_all

    classic_results = benchmark_classic(
        command=args.command,
        model=args.model,
        allow_all=allow_all,
        prompt=args.prompt,
        runs=args.runs,
        cwd=cwd,
        timeout_seconds=args.timeout_seconds,
    )
    acp_results = benchmark_acp(
        command=args.command,
        model=args.model,
        allow_all=allow_all,
        prompt=args.prompt,
        runs=args.runs,
        cwd=cwd,
        timeout_seconds=args.timeout_seconds,
        fresh_session_per_run=args.fresh_acp_session_per_run,
    )

    if args.json:
        classic = _summary(classic_results)
        acp = _summary(acp_results)
        payload = {
            "prompt": args.prompt,
            "runs": args.runs,
            "fresh_acp_session_per_run": args.fresh_acp_session_per_run,
            "classic_runs_seconds": [r.seconds for r in classic_results],
            "acp_runs_seconds": [r.seconds for r in acp_results],
            "classic_summary_seconds": classic,
            "acp_summary_seconds": acp,
            "mean_improvement_seconds": classic["mean"] - acp["mean"],
            "mean_speedup_x": (classic["mean"] / acp["mean"]) if acp["mean"] > 0 else None,
        }
        print(json.dumps(payload, indent=2))
        return 0

    _print_report(
        classic_results=classic_results,
        acp_results=acp_results,
        prompt=args.prompt,
        fresh_session_per_run=args.fresh_acp_session_per_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
