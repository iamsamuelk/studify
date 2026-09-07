"""
eval_pipeline_results.py

Generates pipeline_results.csv covering:
  - Table 4.14 (end-to-end latency by stage) -- fully automatic, real data.
  - Tables 4.12/4.13 (explanation quality) -- real explanations from the
    live pipeline, scored by an LLM-as-judge. THIS IS A METHODOLOGY
    CHOICE YOU MUST DISCLOSE IN THE REPORT, not a substitute you can
    silently swap in for human raters (see the big warning below).
  - Table 4.17 (Studify vs a general-purpose LLM) -- requires the actual
    38-item test bank from Tables 4.6-4.8, which was not available when
    this script was written. See run_table_4_17() -- it will refuse to
    run with a placeholder/synthetic bank rather than silently pad the
    30-item interpretation bank up to 38.

=====================================================================
IMPORTANT: read this before you touch Tables 4.12/4.13
=====================================================================
The report's rubric (fidelity, correctness of intermediate steps, rule
identification, logical structure, clarity) is a HUMAN judgment
instrument. Using an LLM to score against it is a real, published
technique in NLP evaluation research ("LLM-as-judge"), and it produces
real, non-fabricated numbers -- but it is not the same instrument as
human raters, and presenting LLM-judge scores as if a person filled out
the rubric would be misrepresenting your methodology.

If you use this:
  1. Say so explicitly in your methodology section: "explanation
     quality was scored by an LLM judge (specify model) against the
     rubric in Table 4.11, as a scalable proxy for human evaluation."
  2. Get at least a handful of real human ratings on a SUBSET of the
     explanations (even 5-10) and report the agreement between the
     human and LLM scores. This is exactly the "inter-rater agreement"
     the report's own NOTE TO AUTHOR under Table 4.13 asks for -- it
     just usually assumes two humans, and here one "rater" is the LLM.
  3. Do not present the LLM judge as a second independent human rater.
  4. The judge model (qwen/qwen3.6-plus-preview:free via OpenRouter) is
     free during a preview period; OpenRouter's own terms state prompts
     and completions may be collected to improve the model during this
     period. That's your queries and Studify's generated explanations,
     not anything more sensitive, but worth knowing before you send
     academic work through a free preview endpoint.

If you'd rather not do LLM-as-judge at all, skip run_explanation_quality()
and get human ratings only -- see the standalone rubric-scoring sheet
suggested separately.

=====================================================================
Quota budget (checked against your live dashboard, 2026-09-07):
=====================================================================
  gemini-3.5-flash-lite / 3.1-flash-lite (parser)    : RPM 15, RPD 500
  gemini-3.6-flash / 3.8-flash (explainer, fallback) : RPM  5, RPD  20 each

Table 4.14 needs 30 full-pipeline calls (one per query, no repeats --
the table's Mean/Min/Max are computed ACROSS the 30 different queries,
not across repeated runs of the same query). That's within a single
day's combined explainer budget (20-40 depending on what's already
been used today), but leaves little room for Table 4.12/4.13's own
explanation generation unless you reuse the SAME 30 explanations
collected here rather than generating a second batch. This script
does exactly that: run_latency() and run_explanation_quality() share
one collection pass so the explainer is only called once per query
across both tables.

Usage:
    pip install requests --break-system-packages
    export OPENROUTER_API_KEY=...   # only needed for LLM-as-judge scoring
                                     # free tier: sign up at openrouter.ai,
                                     # judge model is qwen/qwen3.6-plus-preview:free
    python eval_pipeline_results.py
"""

import csv
import os
import time
import requests

BASE_URL = "https://studify.quikdb.net"
SOLVE_ENDPOINT = "/solve"
DELAY_BETWEEN_CALLS_S = 13.0  # explainer RPM=5 -> min 12s spacing, +margin

TEST_BANK = [
    ("Q01", "Simple", "Differentiate x cubed plus 3x squared plus 2x", "derivative"),
    ("Q02", "Simple", "What is the derivative of sin(x)?", "derivative"),
    ("Q03", "Simple", "Integrate 2x", "indefinite_integral"),
    ("Q04", "Simple", "Find the integral of cos x dx", "indefinite_integral"),
    ("Q05", "Simple", "Integrate x squared from 0 to 3", "definite_integral"),
    ("Q06", "Simple", "Solve x squared minus 9 equals zero", "solve"),
    ("Q07", "Simple", "Simplify (x^2 - 1)/(x - 1)", "simplify"),
    ("Q08", "Simple", "Laplace transform of 1", "laplace"),
    ("Q09", "Simple", "Find the limit of sin(x)/x as x approaches 0", "limit"),
    ("Q10", "Simple", "Inverse Laplace transform of 1/s", "inverse_laplace"),
    ("Q11", "Intermediate", "Differentiate x squared times e to the x", "derivative"),
    ("Q12", "Intermediate", "d/dx of sin(x^2)", "derivative"),
    ("Q13", "Intermediate", "Integrate sin(x) from 0 to pi", "definite_integral"),
    ("Q14", "Intermediate", "Evaluate the integral of e^(-x) between 0 and infinity", "definite_integral"),
    ("Q15", "Intermediate", "Integrate x e^x with respect to x", "indefinite_integral"),
    ("Q16", "Intermediate", "limit of (1 + 1/x)^x as x tends to infinity", "limit"),
    ("Q17", "Intermediate", "Find the roots of x^2 + 4x + 4", "solve"),
    ("Q18", "Intermediate", "Taylor series of sin(x) about 0", "taylor"),
    ("Q19", "Intermediate", "Laplace transform of e to the power negative 2t", "laplace"),
    ("Q20", "Intermediate", "Find the Laplace transform of t squared", "laplace"),
    ("Q21", "Intermediate", "Inverse Laplace of 1 over s plus 2", "inverse_laplace"),
    ("Q22", "Intermediate", "Simplify sin squared x plus cos squared x", "simplify"),
    ("Q23", "Multi-step", "Differentiate ln(x) divided by x", "derivative"),
    ("Q24", "Multi-step", "Differentiate e^(-2t) cos(3t) with respect to t", "derivative"),
    ("Q25", "Multi-step", "Integrate 1/(x^2 - 1) using partial fractions", "indefinite_integral"),
    ("Q26", "Multi-step", "Integrate x sin x from 0 to pi", "definite_integral"),
    ("Q27", "Multi-step", "Solve the cubic x^3 - 6x^2 + 11x - 6 = 0", "solve"),
    ("Q28", "Multi-step", "Expand ln(1+x) as a Taylor series about 0 up to order 5", "taylor"),
    ("Q29", "Multi-step", "Laplace transform of t e^(-t)", "laplace"),
    ("Q30", "Multi-step", "Find the inverse Laplace transform of 1/(s^2 + 3s + 2)", "inverse_laplace"),
]

RUBRIC_CRITERIA = {
    "a_fidelity": "Fidelity to the verified symbolic result -- does the explanation's stated final answer exactly match the verified symbolic result, with no invented or altered values?",
    "b_intermediate_steps": "Correctness of intermediate steps -- is every intermediate algebraic/calculus step mathematically valid?",
    "c_rule_identification": "Rule identification -- does the explanation correctly name the mathematical rule(s) used (e.g. product rule, linearity of the Laplace transform)?",
    "d_logical_structure": "Logical structure and completeness -- is the explanation a complete, logically ordered derivation rather than a list of disconnected facts?",
    "e_clarity": "Clarity and conceptual note -- is the explanation clear to an undergraduate engineering student, and does it include a conceptual note connecting the result to its engineering relevance?",
}


MAX_RETRIES_ON_429 = 3
BASE_BACKOFF_S = 20.0  # 20s, 40s, 80s


def is_rate_limit_error(exc_or_payload):
    text = str(exc_or_payload)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower()


def call_solve(query):
    """
    POSTs to /solve with retry+backoff on 429, whether it surfaces as an
    HTTP-level error or as success=False with a quota message embedded
    in a 200 response (the pipeline can catch the Gemini exception
    internally -- see the nlp_parser/explainer fallback logic).
    Given the explainer's tight daily quota, a dropped query here is
    expensive to redo, so this is worth retrying rather than skipping.
    """
    url = BASE_URL.rstrip("/") + SOLVE_ENDPOINT
    last_error = None

    for attempt in range(MAX_RETRIES_ON_429 + 1):
        t0 = time.perf_counter()
        try:
            resp = requests.post(url, json={"query": query, "skip_explanation": False}, timeout=90)
            elapsed = time.perf_counter() - t0

            if resp.status_code == 429:
                last_error = f"HTTP 429: {resp.text[:300]}"
                if attempt < MAX_RETRIES_ON_429:
                    backoff = BASE_BACKOFF_S * (2 ** attempt)
                    print(f"  HTTP 429, retrying in {backoff:.0f}s (attempt {attempt+1}/{MAX_RETRIES_ON_429})")
                    time.sleep(backoff)
                    continue
                return {}, elapsed, last_error

            resp.raise_for_status()
            data = resp.json()

            if data.get("success") is False and is_rate_limit_error(data.get("error")):
                last_error = data.get("error")
                if attempt < MAX_RETRIES_ON_429:
                    backoff = BASE_BACKOFF_S * (2 ** attempt)
                    print(f"  Quota error in payload, retrying in {backoff:.0f}s (attempt {attempt+1}/{MAX_RETRIES_ON_429})")
                    time.sleep(backoff)
                    continue
                return data, elapsed, last_error

            return data, elapsed, None

        except requests.exceptions.RequestException as e:
            elapsed = time.perf_counter() - t0
            last_error = str(e)
            if is_rate_limit_error(e) and attempt < MAX_RETRIES_ON_429:
                backoff = BASE_BACKOFF_S * (2 ** attempt)
                print(f"  Request error (possible 429), retrying in {backoff:.0f}s (attempt {attempt+1}/{MAX_RETRIES_ON_429})")
                time.sleep(backoff)
                continue
            return {}, elapsed, last_error

    return {}, None, last_error


def collect_pipeline_runs():
    """
    Runs the full pipeline (with explanation) once per query in TEST_BANK.
    Shared by both run_latency() and run_explanation_quality() so the
    explainer's tight quota is only spent once per query.
    """
    results = []
    for idx, (qid, level, query, op) in enumerate(TEST_BANK, start=1):
        print(f"[{qid}] ({idx}/{len(TEST_BANK)}) {query}")
        data, round_trip, error = call_solve(query)
        if error:
            print(f"  FAILED: {error[:150]}")

        results.append({
            "ID": qid,
            "Level": level,
            "Query": query,
            "Operation": op,
            "success": data.get("success"),
            "error": data.get("error") or error,
            "symbolic_result": data.get("symbolic_result"),
            "explanation": data.get("explanation"),
            "interpretation_time_s": data.get("interpretation_time_s"),
            "symbolic_time_s": data.get("symbolic_time_s"),
            "explanation_time_s": data.get("explanation_time_s"),
            "round_trip_time_s": round(round_trip, 3) if round_trip else None,
        })
        time.sleep(DELAY_BETWEEN_CALLS_S)
    return results


def run_latency(results):
    """Table 4.14: mean/min/max per stage, share of total, across the 30 queries."""
    stages = {
        "Interpretation": [r["interpretation_time_s"] for r in results if r["interpretation_time_s"] is not None],
        "Symbolic computation": [r["symbolic_time_s"] for r in results if r["symbolic_time_s"] is not None],
        "Explanation": [r["explanation_time_s"] for r in results if r["explanation_time_s"] is not None],
    }
    totals = [r["round_trip_time_s"] for r in results if r["round_trip_time_s"] is not None]
    grand_total_mean = sum(totals) / len(totals) if totals else None

    print("\n=== TABLE 4.14: END-TO-END LATENCY BY PIPELINE STAGE ===")
    for stage, times in stages.items():
        if not times:
            print(f"{stage}: no data")
            continue
        mean_t = sum(times) / len(times)
        line = f"{stage}: mean={mean_t:.3f}s min={min(times):.3f}s max={max(times):.3f}s"
        if grand_total_mean:
            share = mean_t / grand_total_mean * 100
            line += f" share={share:.1f}%"
        print(line)
    if totals:
        print(f"Total (server side): mean={grand_total_mean:.3f}s min={min(totals):.3f}s "
              f"max={max(totals):.3f}s share=100%")


JUDGE_MODEL = "qwen/qwen3.6-plus-preview:free"
JUDGE_MAX_RETRIES_ON_429 = 3
JUDGE_BASE_BACKOFF_S = 10.0


def score_explanation_with_llm_judge(query, operation, symbolic_result, explanation):
    """
    LLM-as-judge scoring against the Table 4.11/4.12 rubric, using
    qwen/qwen3.6-plus-preview:free via OpenRouter as an INDEPENDENT judge
    model (deliberately not Gemini, since Gemini generated the
    explanation being judged -- using the same model family to grade
    its own work would be a weaker, self-evaluation design).

    Requires OPENROUTER_API_KEY. This is a free-tier/preview model, so:
      - it can be rate limited under load (retried with backoff below)
      - "free" status is time-limited on OpenRouter's side; if this
        model stops being free or gets deprecated, check
        https://openrouter.ai/qwen for a current free alternative and
        update JUDGE_MODEL above -- don't silently fall back to a paid
        model without deciding that's what you want.

    Returns a dict of scores 1-5 per criterion, or None if the API key
    isn't set (caller should skip scoring, not fabricate a score).
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    rubric_text = "\n".join(f"({k[0]}) {v}" for k, v in RUBRIC_CRITERIA.items())
    prompt = f"""You are scoring a step-by-step math explanation produced by an automated tutoring system, against this rubric. Score each criterion 1-5 (5 = excellent).

Rubric:
{rubric_text}

Original query: {query}
Operation: {operation}
Verified symbolic result (ground truth): {symbolic_result}

Explanation to score:
---
{explanation}
---

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"a_fidelity": <1-5>, "b_intermediate_steps": <1-5>, "c_rule_identification": <1-5>, "d_logical_structure": <1-5>, "e_clarity": <1-5>}}"""

    import json as _json
    last_error = None

    for attempt in range(JUDGE_MAX_RETRIES_ON_429 + 1):
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": JUDGE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )

        if resp.status_code == 429:
            last_error = f"HTTP 429: {resp.text[:300]}"
            if attempt < JUDGE_MAX_RETRIES_ON_429:
                backoff = JUDGE_BASE_BACKOFF_S * (2 ** attempt)
                print(f"    Judge model 429, retrying in {backoff:.0f}s "
                      f"(attempt {attempt+1}/{JUDGE_MAX_RETRIES_ON_429})")
                time.sleep(backoff)
                continue
            raise RuntimeError(last_error)

        resp.raise_for_status()
        body = resp.json()

        if "choices" not in body or not body["choices"]:
            raise RuntimeError(f"Unexpected judge response shape: {body}")

        text = body["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return _json.loads(text.strip())

    raise RuntimeError(last_error)


def run_explanation_quality(results):
    """Tables 4.12/4.13: rubric scores per criterion and per operation."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("\nOPENROUTER_API_KEY not set -- skipping explanation quality scoring "
              "(Tables 4.12/4.13). Set the key (free signup at openrouter.ai) and "
              "rerun, or collect human ratings instead using the rubric in Table 4.11.")
        return []

    scored = []
    for r in results:
        if not r.get("success") or not r.get("explanation"):
            continue
        print(f"Scoring {r['ID']}...")
        try:
            scores = score_explanation_with_llm_judge(
                r["Query"], r["Operation"], r.get("symbolic_result", ""), r["explanation"]
            )
        except Exception as e:
            print(f"  scoring failed: {e}")
            scores = None
        if scores:
            row = dict(r)
            row.update(scores)
            row["overall"] = round(sum(scores.values()) / len(scores), 2)
            scored.append(row)
        time.sleep(3)  # free-tier judge model -- more conservative than a paid API

    if scored:
        print("\n=== TABLE 4.12: MEAN SCORES BY CRITERION ===")
        for crit in RUBRIC_CRITERIA:
            vals = [row[crit] for row in scored]
            mean_v = sum(vals) / len(vals)
            sd = (sum((v - mean_v) ** 2 for v in vals) / len(vals)) ** 0.5
            pct_high = 100 * sum(1 for v in vals if v >= 4) / len(vals)
            print(f"{crit}: mean={mean_v:.2f} sd={sd:.2f} pct_4_or_5={pct_high:.1f}%")

        print("\n=== TABLE 4.13: MEAN SCORES BY OPERATION ===")
        ops = sorted(set(row["Operation"] for row in scored))
        for op in ops:
            subset = [row["overall"] for row in scored if row["Operation"] == op]
            print(f"{op}: n={len(subset)} mean_overall={sum(subset)/len(subset):.2f}")

    return scored


def run_table_4_17(test_bank_38_path=None):
    """
    Table 4.17 needs the ACTUAL 38-item symbolic-engine test bank from
    Tables 4.6-4.8, which this script does not have. Provide it as a CSV
    with columns: id, level, query, expected_final_answer, then pass its
    path here. This function deliberately does NOT fall back to the
    30-item interpretation bank -- reusing or padding that bank would
    misrepresent the 38-problem test set referenced in the report.
    """
    if not test_bank_38_path or not os.path.exists(test_bank_38_path):
        print("\nTable 4.17 skipped: no 38-item test bank provided. "
              "Export the test bank used in Tables 4.6-4.8 to a CSV "
              "(id, level, query, expected_final_answer) and pass its "
              "path to run_table_4_17().")
        return
    # Implementation intentionally left for once the real bank is supplied --
    # ask before building the comparison logic against ambiguous ground truth.
    raise NotImplementedError("Real 38-item test bank found -- ask for comparison logic to be completed.")


def write_csv(results, scored, path="pipeline_results.csv"):
    scored_by_id = {row["ID"]: row for row in scored}
    fieldnames = list(results[0].keys()) + list(RUBRIC_CRITERIA.keys()) + ["overall"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = dict(r)
            if r["ID"] in scored_by_id:
                for crit in RUBRIC_CRITERIA:
                    row[crit] = scored_by_id[r["ID"]][crit]
                row["overall"] = scored_by_id[r["ID"]]["overall"]
            writer.writerow(row)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    results = collect_pipeline_runs()
    run_latency(results)
    scored = run_explanation_quality(results)
    write_csv(results, scored)
    run_table_4_17(test_bank_38_path=None)  # pass the real 38-item CSV path once available
