"""Automated evaluation benchmark CLI and LangSmith Experiments for Getnet Multi-Agent Support."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langsmith.evaluation import EvaluationResult

from src.config.settings import settings
from src.observability.logger import get_logger
from src.orchestration.graph import execute_orchestration

logger = get_logger("evaluation.benchmark")


def _get_run_outputs(run: Any) -> dict[str, Any]:
    """Extract outputs dictionary from a LangSmith Run or dict."""
    if hasattr(run, "outputs") and isinstance(run.outputs, dict):
        return run.outputs
    if isinstance(run, dict):
        return run.get("outputs", run)
    return {}


def _get_example_outputs(example: Any) -> dict[str, Any]:
    """Extract expected outputs dictionary from a LangSmith Example or dict."""
    if hasattr(example, "outputs") and isinstance(example.outputs, dict):
        return example.outputs
    if isinstance(example, dict):
        return example.get("outputs", example)
    return {}


def _get_example_inputs(example: Any) -> dict[str, Any]:
    """Extract inputs dictionary from a LangSmith Example or dict."""
    if hasattr(example, "inputs") and isinstance(example.inputs, dict):
        return example.inputs
    if isinstance(example, dict):
        return example.get("inputs", example)
    return {}


def eval_routing_accuracy(run: Any, example: Any) -> EvaluationResult:
    """Evaluator 1: score 1.0 if routed_agents strictly equals expected_agents, else 0.0."""
    actual = _get_run_outputs(run).get("routed_agents", [])
    expected = _get_example_outputs(example).get("expected_agents", [])
    is_match = actual == expected
    score = 1.0 if is_match else 0.0
    return EvaluationResult(
        key="routing_accuracy",
        score=score,
        comment=f"expected={expected}, actual={actual}",
    )


def eval_tool_accuracy(run: Any, example: Any) -> EvaluationResult:
    """Evaluator 2: score tool selection accuracy against expected challenge tools."""
    actual = _get_run_outputs(run).get("tools_used", [])
    expected = _get_example_outputs(example).get("expected_tools", [])
    if not expected:
        score = 1.0
    else:
        hits = sum(1 for t in expected if t in actual)
        score = round(hits / len(expected), 3)
    return EvaluationResult(
        key="tool_accuracy",
        score=score,
        comment=f"expected={expected}, actual={actual}",
    )


def eval_rubric_groundedness(run: Any, example: Any) -> EvaluationResult:
    """Evaluator 3: score factual groundedness, keywords, and safety/handoff constraints."""
    run_out = _get_run_outputs(run)
    ex_out = _get_example_outputs(example)

    response = str(run_out.get("response", "")).lower()
    keywords = ex_out.get("expected_keywords", [])
    if keywords:
        hits = sum(1 for kw in keywords if kw.lower() in response)
        kw_score = hits / len(keywords)
    else:
        kw_score = 1.0

    guardrail_ok = run_out.get("guardrail_triggered", False) == ex_out.get(
        "expect_guardrail_block", False
    )
    handoff_ok = run_out.get("handoff_required", False) == ex_out.get(
        "expect_handoff", False
    )

    combined_score = kw_score if (guardrail_ok and handoff_ok) else (kw_score * 0.5)
    return EvaluationResult(
        key="rubric_groundedness",
        score=round(combined_score, 3),
        comment=f"keywords_matched={kw_score:.2f}, guardrail_ok={guardrail_ok}, handoff_ok={handoff_ok}",
    )


def eval_llm_faithfulness(run: Any, example: Any) -> EvaluationResult:
    """Evaluator 4: LLM-as-a-judge assessing factual faithfulness, tone, and hallucination."""
    run_out = _get_run_outputs(run)
    ex_out = _get_example_outputs(example)
    ex_in = _get_example_inputs(example)

    if settings.has_openai_key:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=0.0,
                api_key=settings.openai_api_key,
                timeout=8.0,
                max_retries=1,
            )
            prompt = (
                "You are an impartial evaluation judge for a customer support AI assistant.\n"
                f"User Question: {ex_in.get('message', '')}\n"
                f"Ground-Truth Expected Keywords/Facts: {ex_out.get('expected_keywords', [])}\n"
                f"Assistant Response: {run_out.get('response', '')}\n\n"
                "Evaluate whether the response is factually faithful, grounded in the facts, and free of hallucinations.\n"
                "Reply with ONLY a JSON object: {\"score\": <float in [0.0, 1.0]>, \"reason\": \"<short justification>\"}"
            )
            judge_res = llm.invoke(
                [
                    SystemMessage(content="You are an impartial evaluation judge."),
                    HumanMessage(content=prompt),
                ]
            )
            match = re.search(r"\{.*\}", str(judge_res.content), re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                score = float(parsed.get("score", 1.0))
                reason = str(parsed.get("reason", "LLM judged faithful."))
                return EvaluationResult(key="llm_faithfulness", score=score, comment=reason)
        except Exception as exc:
            logger.warning("llm_faithfulness_judge_fallback", error=str(exc))

    # Deterministic fallback when OpenAI API is not available
    fallback_res = eval_rubric_groundedness(run, example)
    return EvaluationResult(
        key="llm_faithfulness",
        score=fallback_res.score,
        comment="Deterministic groundedness fallback (offline/no API key)",
    )


def evaluate_dataset(
    sync_langsmith: bool = False,
    max_scenarios: int | None = None,
) -> dict[str, Any]:
    """Run evaluation scenarios locally and optionally trigger a formal LangSmith Experiment."""
    dataset_path = settings.resolve_path(settings.eval_dataset_path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    all_scenarios: list[dict[str, Any]] = list(payload.get("scenarios") or [])
    scenarios = all_scenarios[:max_scenarios] if max_scenarios else all_scenarios

    results: list[dict[str, Any]] = []
    route_hits = 0
    tool_hits = 0
    rubric_hits = 0
    total_tokens_all = 0

    for item in scenarios:
        out = execute_orchestration(
            message=item["message"],
            user_id=item["user_id"],
        )

        mock_run = {"outputs": out}
        mock_example = {
            "inputs": {"message": item["message"], "user_id": item["user_id"]},
            "outputs": item,
        }

        r_eval = eval_routing_accuracy(mock_run, mock_example)
        t_eval = eval_tool_accuracy(mock_run, mock_example)
        g_eval = eval_rubric_groundedness(mock_run, mock_example)
        f_eval = eval_llm_faithfulness(mock_run, mock_example)

        route_ok = r_eval.score == 1.0
        tools_ok = t_eval.score == 1.0
        rubric_ok = g_eval.score == 1.0

        if route_ok:
            route_hits += 1
        if tools_ok:
            tool_hits += 1
        if rubric_ok:
            rubric_hits += 1

        tokens_consumed = int(out.get("total_tokens") or 0)
        total_tokens_all += tokens_consumed

        results.append(
            {
                "id": item["id"],
                "category": item["category"],
                "message": item["message"],
                "route_ok": route_ok,
                "tools_ok": tools_ok,
                "rubric_ok": rubric_ok,
                "routing_accuracy": r_eval.score,
                "tool_accuracy": t_eval.score,
                "rubric_groundedness": g_eval.score,
                "faithfulness_score": f_eval.score,
                "routed_agents": out["routed_agents"],
                "tools_used": out["tools_used"],
                "latency_ms": out["latency_ms"],
                "total_tokens": tokens_consumed,
                "trace_id": out["trace_id"],
            }
        )

    total = len(scenarios)
    summary = {
        "dataset_name": payload.get("dataset_name", "getnet-multi-agent-eval-v1"),
        "total_scenarios": total,
        "official_10_scenarios_passed": sum(
            1
            for r in results[:10]
            if r["route_ok"] and r["tools_ok"] and r["rubric_ok"]
        ),
        "routing_accuracy_pct": round((route_hits / total) * 100.0, 2) if total else 0.0,
        "tool_accuracy_pct": round((tool_hits / total) * 100.0, 2) if total else 0.0,
        "rubric_groundedness_pct": round((rubric_hits / total) * 100.0, 2) if total else 0.0,
        "average_latency_ms": round(
            sum(r["latency_ms"] for r in results) / total, 2
        )
        if total
        else 0.0,
        "total_tokens_consumed": total_tokens_all,
        "average_tokens_per_request": round(total_tokens_all / total, 1) if total else 0.0,
        "scenarios": results,
    }

    # LangSmith Experiment execution
    if sync_langsmith and settings.langsmith_enabled:
        try:
            from langsmith import Client
            from langsmith.evaluation import evaluate

            client = Client()
            ds_name = str(payload.get("dataset_name", "getnet-multi-agent-eval-v1"))

            if not client.has_dataset(dataset_name=ds_name):
                ds = client.create_dataset(
                    dataset_name=ds_name,
                    description="Official Getnet multi-agent 10 challenge scenarios + bonus cases",
                )
                for item in scenarios:
                    client.create_example(
                        inputs={"message": item["message"], "user_id": item["user_id"]},
                        outputs={
                            "expected_agents": item["expected_agents"],
                            "expected_tools": item["expected_tools"],
                            "expected_keywords": item["expected_keywords"],
                            "expect_guardrail_block": item.get("expect_guardrail_block", False),
                            "expect_handoff": item.get("expect_handoff", False),
                        },
                        dataset_id=ds.id,
                    )

            def predict_fn(inputs: dict[str, Any]) -> dict[str, Any]:
                return execute_orchestration(
                    message=inputs["message"],
                    user_id=inputs.get("user_id", "cliente1988"),
                )

            experiment_results = evaluate(
                predict_fn,
                data=ds_name,
                evaluators=[
                    eval_routing_accuracy,
                    eval_tool_accuracy,
                    eval_rubric_groundedness,
                    eval_llm_faithfulness,
                ],
                experiment_prefix="getnet-multi-agent",
                description="Getnet Multi-Agent Challenge Scenarios Evaluation Experiment",
                max_concurrency=1,
            )

            exp_name = str(getattr(experiment_results, "experiment_name", "getnet-multi-agent"))
            summary["langsmith_dataset_synced"] = True
            summary["langsmith_experiment_name"] = exp_name
            logger.info("langsmith_experiment_completed", experiment_name=exp_name)
        except Exception as exc:
            logger.warning("langsmith_evaluation_sync_failed", error=str(exc))
            summary["langsmith_dataset_synced"] = False
            summary["langsmith_sync_error"] = str(exc)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Getnet 10-scenario + bonus evaluation suite with LangSmith Experiment support."
    )
    parser.add_argument(
        "--sync-langsmith",
        action="store_true",
        help="Push dataset and run LangSmith Experiment (langsmith.evaluation.evaluate).",
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=None,
        help="Optional limit on number of scenarios to evaluate.",
    )
    args = parser.parse_args()

    report = evaluate_dataset(
        sync_langsmith=args.sync_langsmith,
        max_scenarios=args.max_scenarios,
    )
    print("=" * 82)
    print(f"Getnet Multi-Agent Evaluation Report — Dataset: {report['dataset_name']}")
    print("=" * 82)
    for row in report["scenarios"]:
        status = "PASS" if (row["route_ok"] and row["tools_ok"] and row["rubric_ok"]) else "FAIL"
        print(
            f"[{status}] {row['id']} ({row['category']}) | "
            f"agents={row['routed_agents']} | tools={row['tools_used']} | "
            f"tokens={row.get('total_tokens', 0)} | {row['latency_ms']}ms"
        )
    print("-" * 82)
    print(
        f"Official 10 Scenarios: {report['official_10_scenarios_passed']}/10 | "
        f"Routing Accuracy: {report['routing_accuracy_pct']}% | "
        f"Tool Accuracy: {report['tool_accuracy_pct']}% | "
        f"Rubric Groundedness: {report['rubric_groundedness_pct']}% | "
        f"Avg Latency: {report['average_latency_ms']}ms | "
        f"Total Tokens: {report['total_tokens_consumed']}"
    )
    if report.get("langsmith_dataset_synced"):
        print(f"LangSmith Experiment: {report.get('langsmith_experiment_name')}")
    elif report.get("langsmith_sync_error"):
        print(f"LangSmith Notice: {report.get('langsmith_sync_error')}")
    print("=" * 82)

    all_passed = (
        report["routing_accuracy_pct"] == 100.0
        and report["tool_accuracy_pct"] == 100.0
        and report["rubric_groundedness_pct"] == 100.0
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
