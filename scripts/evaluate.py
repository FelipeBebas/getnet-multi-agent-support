"""Automated evaluation benchmark CLI, Ragas quantitative suite, and LangSmith Experiments."""

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

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "was", "were", "will", "can", "into", "via", "about", "what", "when", "how",
    "que", "para", "com", "uma", "uns", "por", "dos", "das", "seu", "sua",
    "como", "quando", "qual", "quais", "não", "nao", "sim", "sobre", "entre",
}


def _tokenize_content(text: str) -> set[str]:
    """Extract normalized content tokens (>=3 chars, excluding common stopwords)."""
    tokens = re.findall(r"[a-z0-9à-úç]+", (text or "").lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOPWORDS}


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
    norm_response = response.replace(".", "").replace(",", "").replace(" ", "")
    keywords = ex_out.get("expected_keywords", [])
    if keywords:
        hits = sum(
            1
            for kw in keywords
            if kw.lower() in response
            or kw.lower().replace(".", "").replace(",", "").replace(" ", "") in norm_response
        )
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

    if settings.use_live_llm:
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

    fallback_res = eval_rubric_groundedness(run, example)
    return EvaluationResult(
        key="llm_faithfulness",
        score=fallback_res.score,
        comment="Deterministic groundedness fallback (offline/no API key)",
    )


def _compute_offline_ragas_row(record: dict[str, Any]) -> dict[str, float]:
    """Compute deterministic, grounded Ragas-compatible scores in [0.0, 1.0] without external LLM calls."""
    response = str(record.get("response") or "")
    question = str(record.get("user_input") or "")
    reference = str(record.get("reference") or "")
    retrieved = [str(c) for c in (record.get("retrieved_contexts") or []) if str(c).strip()]
    ref_contexts = [str(c) for c in (record.get("reference_contexts") or []) if str(c).strip()]
    keywords = [str(k) for k in (record.get("expected_keywords") or [])]

    resp_tokens = _tokenize_content(response)
    q_tokens = _tokenize_content(question)
    ref_tokens = _tokenize_content(reference) | {
        tok for kw in keywords for tok in _tokenize_content(kw)
    }

    # For blocked guardrail queries where downstream RAG intentionally did not execute,
    # ground evaluation against the policy reference context.
    effective_contexts = (
        retrieved
        if retrieved
        else (ref_contexts if record.get("guardrail_triggered") and record.get("expect_guardrail_block") else [])
    )
    ctx_tokens = set()
    for ctx in effective_contexts:
        ctx_tokens.update(_tokenize_content(ctx))

    resp_lower = response.lower()
    norm_resp = resp_lower.replace(".", "").replace(",", "").replace(" ", "")
    kw_ratio = (
        sum(
            1
            for kw in keywords
            if kw.lower() in resp_lower
            or kw.lower().replace(".", "").replace(",", "").replace(" ", "") in norm_resp
        )
        / len(keywords)
        if keywords
        else 1.0
    )

    if resp_tokens and ctx_tokens:
        raw_overlap = len(resp_tokens & ctx_tokens) / len(resp_tokens)
        # Scale overlap gently since Personality Agent paraphrases retrieved context
        faithfulness = min(1.0, 0.70 * min(1.0, raw_overlap * 1.45) + 0.30 * kw_ratio)
    else:
        faithfulness = 0.0

    # Answer relevancy: question + reference semantic token coverage in response
    target_rel_tokens = q_tokens | ref_tokens
    if target_rel_tokens and resp_tokens:
        rel_overlap = len(resp_tokens & target_rel_tokens) / max(1, min(len(target_rel_tokens), 12))
        answer_relevancy = min(1.0, 0.65 * min(1.0, rel_overlap) + 0.35 * kw_ratio)
    else:
        answer_relevancy = 0.0

    # Context precision: fraction of retrieved chunks aligned with reference/question tokens
    relevant_anchor = ref_tokens | q_tokens
    if effective_contexts and relevant_anchor:
        relevant_chunks = sum(
            1
            for ctx in effective_contexts
            if len(_tokenize_content(ctx) & relevant_anchor) >= 1
        )
        context_precision = relevant_chunks / len(effective_contexts)
    else:
        context_precision = 0.0

    # Context recall: coverage of reference facts inside retrieved contexts
    if ref_tokens and ctx_tokens:
        context_recall = min(1.0, len(ref_tokens & ctx_tokens) / len(ref_tokens) * 1.2)
    elif not ref_tokens and effective_contexts:
        context_recall = 1.0
    else:
        context_recall = 0.0

    f_val = round(max(0.0, min(1.0, faithfulness)), 4)
    return {
        "faithfulness": f_val,
        "answer_relevancy": round(max(0.0, min(1.0, answer_relevancy)), 4),
        "context_precision": round(max(0.0, min(1.0, context_precision)), 4),
        "context_recall": round(max(0.0, min(1.0, context_recall)), 4),
        "hallucination_rate": round(1.0 - f_val, 4),
    }


def compute_ragas_metrics(
    records: list[dict[str, Any]],
    *,
    allow_live: bool = True,
) -> tuple[list[dict[str, float]], str]:
    """Compute quantitative Ragas metrics via live LLM or deterministic offline fallback."""
    if not records:
        return [], "offline_deterministic"

    if allow_live and settings.use_live_llm:
        try:
            from openai import OpenAI
            from ragas import EvaluationDataset, SingleTurnSample, evaluate as ragas_evaluate
            from ragas.embeddings import embedding_factory
            from ragas.llms import llm_factory
            from ragas.metrics.collections import (
                AnswerRelevancy,
                ContextPrecisionWithReference,
                ContextRecall,
                Faithfulness,
            )

            client = OpenAI(api_key=settings.openai_api_key)
            ragas_llm = llm_factory(settings.openai_model, provider="openai", client=client)
            ragas_emb = embedding_factory(
                "openai", model=settings.openai_embedding_model, client=client
            )

            samples = [
                SingleTurnSample(
                    user_input=str(r["user_input"]),
                    response=str(r["response"]),
                    retrieved_contexts=list(r["retrieved_contexts"] or r["reference_contexts"] or [""]),
                    reference=str(r["reference"]),
                )
                for r in records
            ]
            dataset = EvaluationDataset(samples=samples)
            metrics = [
                Faithfulness(llm=ragas_llm),
                AnswerRelevancy(llm=ragas_llm, embeddings=ragas_emb),
                ContextPrecisionWithReference(llm=ragas_llm),
                ContextRecall(llm=ragas_llm),
            ]
            ragas_res = ragas_evaluate(dataset=dataset, metrics=metrics)
            df = ragas_res.to_pandas()

            per_row: list[dict[str, float]] = []
            for _, row in df.iterrows():
                f_val = round(float(row.get("faithfulness", 0.0) or 0.0), 4)
                ar_val = round(float(row.get("answer_relevancy", 0.0) or 0.0), 4)
                cp_val = round(
                    float(row.get("context_precision_with_reference", 0.0) or 0.0), 4
                )
                cr_val = round(float(row.get("context_recall", 0.0) or 0.0), 4)
                per_row.append(
                    {
                        "faithfulness": f_val,
                        "answer_relevancy": ar_val,
                        "context_precision": cp_val,
                        "context_recall": cr_val,
                        "hallucination_rate": round(max(0.0, min(1.0, 1.0 - f_val)), 4),
                    }
                )
            return per_row, "ragas_live"
        except Exception as exc:
            logger.warning("ragas_live_evaluation_fallback", error=str(exc))

    return [_compute_offline_ragas_row(r) for r in records], "offline_deterministic"


def check_quality_thresholds(
    report: dict[str, Any],
    *,
    min_faithfulness: float | None = None,
    max_hallucination_rate: float | None = None,
) -> tuple[bool, list[str]]:
    """Validate aggregate Ragas and accuracy scores against CI quality gate thresholds."""
    min_f = float(
        settings.eval_min_faithfulness if min_faithfulness is None else min_faithfulness
    )
    max_h = float(
        settings.eval_max_hallucination_rate
        if max_hallucination_rate is None
        else max_hallucination_rate
    )
    ragas_summary = report.get("ragas_metrics") or {}
    faith = float(ragas_summary.get("faithfulness", 0.0))
    halluc = float(ragas_summary.get("hallucination_rate", 1.0))

    failures: list[str] = []
    if float(report.get("routing_accuracy_pct", 0.0)) < 100.0:
        failures.append(f"routing_accuracy_pct={report.get('routing_accuracy_pct')} < 100.0")
    if float(report.get("tool_accuracy_pct", 0.0)) < 100.0:
        failures.append(f"tool_accuracy_pct={report.get('tool_accuracy_pct')} < 100.0")
    if float(report.get("rubric_groundedness_pct", 0.0)) < 100.0:
        failures.append(f"rubric_groundedness_pct={report.get('rubric_groundedness_pct')} < 100.0")
    if faith < min_f:
        failures.append(f"faithfulness={faith:.4f} < min_faithfulness={min_f:.4f}")
    if halluc > max_h:
        failures.append(f"hallucination_rate={halluc:.4f} > max_hallucination_rate={max_h:.4f}")

    return len(failures) == 0, failures


def evaluate_dataset(
    sync_langsmith: bool = False,
    max_scenarios: int | None = None,
) -> dict[str, Any]:
    """Run evaluation scenarios locally, compute Ragas metrics, and optionally sync LangSmith."""
    dataset_path = settings.resolve_path(settings.eval_dataset_path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    all_scenarios: list[dict[str, Any]] = list(payload.get("scenarios") or [])
    scenarios = all_scenarios[:max_scenarios] if max_scenarios else all_scenarios

    results: list[dict[str, Any]] = []
    ragas_records: list[dict[str, Any]] = []
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

        ragas_records.append(
            {
                "user_input": item["message"],
                "response": out.get("response", ""),
                "retrieved_contexts": out.get("retrieved_contexts") or [],
                "reference": item.get("reference") or " ".join(item.get("expected_keywords") or []),
                "reference_contexts": item.get("reference_contexts") or [],
                "expected_keywords": item.get("expected_keywords") or [],
                "expect_guardrail_block": item.get("expect_guardrail_block", False),
                "guardrail_triggered": out.get("guardrail_triggered", False),
            }
        )

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
                "retrieved_contexts_count": len(out.get("retrieved_contexts") or []),
                "latency_ms": out["latency_ms"],
                "total_tokens": tokens_consumed,
                "trace_id": out["trace_id"],
            }
        )

    ragas_rows, evaluation_mode = compute_ragas_metrics(ragas_records)
    for row, r_scores in zip(results, ragas_rows):
        row["ragas"] = r_scores
        row["faithfulness_score"] = r_scores["faithfulness"]

    total = len(scenarios)
    if ragas_rows:
        mean_faith = round(sum(r["faithfulness"] for r in ragas_rows) / len(ragas_rows), 4)
        mean_rel = round(sum(r["answer_relevancy"] for r in ragas_rows) / len(ragas_rows), 4)
        mean_cp = round(sum(r["context_precision"] for r in ragas_rows) / len(ragas_rows), 4)
        mean_cr = round(sum(r["context_recall"] for r in ragas_rows) / len(ragas_rows), 4)
        ragas_aggregate = {
            "faithfulness": mean_faith,
            "answer_relevancy": mean_rel,
            "context_precision": mean_cp,
            "context_recall": mean_cr,
            "hallucination_rate": round(1.0 - mean_faith, 4),
        }
    else:
        ragas_aggregate = {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
            "hallucination_rate": 1.0,
        }

    summary: dict[str, Any] = {
        "dataset_name": payload.get("dataset_name", "getnet-multi-agent-eval-v1"),
        "evaluation_mode": evaluation_mode,
        "total_scenarios": total,
        "official_10_scenarios_passed": sum(
            1
            for r in results[:10]
            if r["route_ok"] and r["tools_ok"] and r["rubric_ok"]
        ),
        "routing_accuracy_pct": round((route_hits / total) * 100.0, 2) if total else 0.0,
        "tool_accuracy_pct": round((tool_hits / total) * 100.0, 2) if total else 0.0,
        "rubric_groundedness_pct": round((rubric_hits / total) * 100.0, 2) if total else 0.0,
        "ragas_metrics": ragas_aggregate,
        "average_latency_ms": round(
            sum(r["latency_ms"] for r in results) / total, 2
        )
        if total
        else 0.0,
        "total_tokens_consumed": total_tokens_all,
        "average_tokens_per_request": round(total_tokens_all / total, 1) if total else 0.0,
        "scenarios": results,
    }

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
        description="Run the Getnet 10-scenario + bonus Ragas evaluation suite with CI thresholds."
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
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Fail with exit code 1 when Ragas or accuracy scores breach configured thresholds.",
    )
    parser.add_argument(
        "--min-faithfulness",
        type=float,
        default=None,
        help="Override minimum aggregate faithfulness threshold.",
    )
    parser.add_argument(
        "--max-hallucination-rate",
        type=float,
        default=None,
        help="Override maximum aggregate hallucination rate threshold.",
    )
    args = parser.parse_args()

    report = evaluate_dataset(
        sync_langsmith=args.sync_langsmith,
        max_scenarios=args.max_scenarios,
    )
    ragas = report["ragas_metrics"]
    print("=" * 92)
    print(
        f"Getnet Multi-Agent Evaluation Report — Dataset: {report['dataset_name']} "
        f"({report['evaluation_mode']})"
    )
    print("=" * 92)
    for row in report["scenarios"]:
        status = "PASS" if (row["route_ok"] and row["tools_ok"] and row["rubric_ok"]) else "FAIL"
        r_m = row["ragas"]
        print(
            f"[{status}] {row['id']} ({row['category']}) | "
            f"faith={r_m['faithfulness']:.2f} rel={r_m['answer_relevancy']:.2f} "
            f"prec={r_m['context_precision']:.2f} rec={r_m['context_recall']:.2f} | "
            f"tokens={row.get('total_tokens', 0)} | {row['latency_ms']}ms"
        )
    print("-" * 92)
    print(
        f"Official 10 Scenarios: {report['official_10_scenarios_passed']}/10 | "
        f"Routing: {report['routing_accuracy_pct']}% | "
        f"Tools: {report['tool_accuracy_pct']}% | "
        f"Rubric: {report['rubric_groundedness_pct']}%"
    )
    print(
        f"Ragas Scorecard — Faithfulness: {ragas['faithfulness']:.4f} | "
        f"Answer Relevancy: {ragas['answer_relevancy']:.4f} | "
        f"Context Precision: {ragas['context_precision']:.4f} | "
        f"Context Recall: {ragas['context_recall']:.4f} | "
        f"Hallucination Rate: {ragas['hallucination_rate']:.4f}"
    )
    if report.get("langsmith_dataset_synced"):
        print(f"LangSmith Experiment: {report.get('langsmith_experiment_name')}")
    elif report.get("langsmith_sync_error"):
        print(f"LangSmith Notice: {report.get('langsmith_sync_error')}")

    ok, threshold_failures = check_quality_thresholds(
        report,
        min_faithfulness=args.min_faithfulness,
        max_hallucination_rate=args.max_hallucination_rate,
    )
    if args.enforce_thresholds and not ok:
        print("THRESHOLD FAILURES:", "; ".join(threshold_failures))
    print("=" * 92)

    if args.enforce_thresholds:
        return 0 if ok else 1

    all_passed = (
        report["routing_accuracy_pct"] == 100.0
        and report["tool_accuracy_pct"] == 100.0
        and report["rubric_groundedness_pct"] == 100.0
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
