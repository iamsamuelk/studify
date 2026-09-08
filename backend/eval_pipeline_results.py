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
  4. The judge model (nvidia/nemotron-3.5-lightning:free via OpenRouter) is
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
  gemini-3.8-flash / 3.7-flash (explainer, fallback) : RPM  5, RPD  20 each

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
                                     # judge model is nvidia/nemotron-3.5-lightning:free
    python eval_pipeline_results.py
"""

import argparse
import csv
import os
import time
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed -- fine if the key is exported in the shell instead

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


def call_solve(query, skip_explanation=False):
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
            resp = requests.post(url, json={"query": query, "skip_explanation": skip_explanation}, timeout=90)
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


JUDGE_MODEL = "nvidia/nemotron-3.5-lightning:free"
JUDGE_MAX_RETRIES_ON_429 = 3
JUDGE_BASE_BACKOFF_S = 10.0


def score_explanation_with_llm_judge(query, operation, symbolic_result, explanation):
    """
    LLM-as-judge scoring against the Table 4.11/4.12 rubric, using
    nvidia/nemotron-3.5-lightning:free via OpenRouter as an INDEPENDENT judge
    model (deliberately not Gemini, since Gemini generated the
    explanation being judged -- using the same model family to grade
    its own work would be a weaker, self-evaluation design).

    Requires OPENROUTER_API_KEY. This is a free-tier/preview model, so:
      - it can be rate limited under load (retried with backoff below)
      - "free" status is time-limited on OpenRouter's side; if this
        model stops being free or gets deprecated, check
        https://openrouter.ai/nvidia for a current free alternative and
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

        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"HTTP {resp.status_code} from OpenRouter -- this means the key "
                f"itself was rejected, not a rate limit. OpenRouter's actual "
                f"error message: {resp.text[:300]}. Common causes: "
                f"OPENROUTER_API_KEY not set/exported in this shell (or sitting "
                f"in a .env file the script isn't loading), the key was copied "
                f"with extra whitespace/quotes, or the key was revoked. Verify "
                f"at https://openrouter.ai/keys before rerunning."
            )

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


def _preflight_check_openrouter_key():
    """
    One cheap call to catch a bad/missing key immediately, instead of
    discovering it 30 identical failures later.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    if not api_key.startswith("sk-or-"):
        masked = f"{api_key[:12]}...{api_key[-4:]}" if len(api_key) > 16 else api_key
        print(f"\n*** OPENROUTER_API_KEY does not look like a valid OpenRouter key ***")
        print(f"Key as loaded: {masked}")
        print("Real OpenRouter keys start with 'sk-or-v1-'. This one is missing "
              "that prefix -- almost certainly copied starting partway through "
              "the key (e.g. from 'v1-...' instead of the full 'sk-or-v1-...'). "
              "Go back to https://openrouter.ai/keys and copy the ENTIRE key "
              "string from the beginning.")
        return False

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": JUDGE_MODEL, "messages": [{"role": "user", "content": "reply with OK"}]},
        timeout=30,
    )
    if resp.status_code in (401, 403):
        masked = f"{api_key[:8]}...{api_key[-4:]}" if api_key and len(api_key) > 12 else "(key looks empty or very short)"
        print(f"\n*** OPENROUTER_API_KEY preflight check FAILED (HTTP {resp.status_code}) ***")
        print(f"Key as loaded by this script: {masked}")
        print(f"OpenRouter's error: {resp.text[:300]}")
        print("Check: is the key actually exported in THIS shell (echo $OPENROUTER_API_KEY), "
              "or sitting in a .env file? Is it copied without extra quotes/whitespace? "
              "Is it still active at https://openrouter.ai/keys?")
        return False
    if resp.status_code >= 400:
        print(f"\nPreflight check got HTTP {resp.status_code} (not an auth problem, "
              f"something else): {resp.text[:300]}")
        return False
    print("OPENROUTER_API_KEY preflight check passed.")
    return True


def run_explanation_quality(results):
    """Tables 4.12/4.13: rubric scores per criterion and per operation."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("\nOPENROUTER_API_KEY not set -- skipping explanation quality scoring "
              "(Tables 4.12/4.13). Set the key (free signup at openrouter.ai) and "
              "rerun, or collect human ratings instead using the rubric in Table 4.11.")
        return []

    if not _preflight_check_openrouter_key():
        print("Aborting explanation quality scoring -- fix the key and rerun "
              "with --stage quality (this makes no /solve calls, so it's free to retry).")
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


def _normalize_answer(s):
    if s is None:
        return None
    return str(s).replace(" ", "").lower()


def answers_match(expected, got):
    """
    Compares a reference answer (from Table 4.6) against a system's
    answer. Tries increasingly loose methods and is explicit about
    uncertainty rather than guessing:

      1. Exact normalized string match.
      2. List-type answers (solve results like "[-3, 3]"): parse as a
         set of sympified elements, compare set equality (order-
         independent).
      3. Scalar symbolic expressions: sympify both sides and check the
         simplified difference is zero.
      4. Anything involving a Taylor series truncation (contains "O(")
         or that fails to parse: NOT auto-verdicted. Returns
         "NEEDS_MANUAL_CHECK" -- sympy's Order arithmetic and small
         formatting differences make automated truncated-series
         comparison unreliable, and silently guessing here would put a
         fabricated correctness verdict into Table 4.17. Report these
         rows as requiring a human look rather than pretending the
         script verified them.

    Returns True, False, or the string "NEEDS_MANUAL_CHECK".
    """
    import sympy as sp

    if expected is None or got is None:
        return False

    if _normalize_answer(expected) == _normalize_answer(got):
        return True

    if "O(" in str(expected) or "O(" in str(got):
        return "NEEDS_MANUAL_CHECK"

    try:
        if str(expected).strip().startswith("[") and str(got).strip().startswith("["):
            def parse_list(s):
                inner = s.strip().strip("[]")
                parts = [p.strip() for p in inner.replace(";", ",").split(",") if p.strip()]
                return set(sp.simplify(sp.sympify(p)) for p in parts)
            return parse_list(expected) == parse_list(got)

        diff = sp.simplify(sp.sympify(expected) - sp.sympify(got))
        return diff == 0
    except Exception:
        return "NEEDS_MANUAL_CHECK"


def call_general_llm(query):
    """
    Asks the free nvidia judge model to solve the problem directly, with
    NO tools/code execution available (a plain chat completion call
    has none by default) -- this is the "general-purpose LLM, tool use
    disabled" comparison the report's methodology note calls for.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"Solve this problem: {query}\n\n"
        "Give your reasoning briefly, then end with a final line in "
        "EXACTLY this format (no other text after it):\n"
        "FINAL ANSWER: <answer in plain math notation, e.g. 3*x**2 + 2 "
        "or [-3, 3] or 1/(s + 2)>"
    )
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": JUDGE_MODEL, "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    if "FINAL ANSWER:" in text:
        return text.split("FINAL ANSWER:")[-1].strip()
    return text.strip()  # fallback: couldn't find the marker, keep raw text for manual review


def run_table_4_17(test_bank_csv_path):
    """
    Table 4.17: final-answer accuracy of Studify vs a general-purpose
    LLM (tool use disabled) on the real 38-item test bank from Tables
    4.6-4.8. Requires OPENROUTER_API_KEY for the general-purpose LLM
    side; Studify's own answers only need the live /solve endpoint.

    Runs the general-purpose LLM TWICE per problem to populate the
    "LLM answers that changed on repetition" column.
    """
    if not test_bank_csv_path or not os.path.exists(test_bank_csv_path):
        print("\nTable 4.17 skipped: no 38-item test bank CSV found at the given path.")
        return []

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("\nTable 4.17 skipped: OPENROUTER_API_KEY not set (needed for the "
              "general-purpose LLM side of the comparison).")
        return []

    with open(test_bank_csv_path) as f:
        bank = list(csv.DictReader(f))

    rows = []
    for idx, item in enumerate(bank, start=1):
        qid, level, query, reference = item["id"], item["level"], item["query"], item["reference_answer"]
        print(f"[{qid}] ({idx}/{len(bank)}) {query}")

        # Studify's final answer only (skip_explanation=True conserves the
        # tight explainer quota, which this table doesn't need at all).
        studify_data, _, studify_err = call_solve(query, skip_explanation=True)
        if studify_err:
            print(f"  Studify call failed: {studify_err[:150]}")

        studify_answer = studify_data.get("symbolic_result")
        studify_correct = answers_match(reference, studify_answer) if studify_data.get("success") else False

        # General-purpose LLM, run twice
        llm_run1 = llm_run2 = None
        try:
            llm_run1 = call_general_llm(query)
            time.sleep(3)
            llm_run2 = call_general_llm(query)
        except Exception as e:
            print(f"  general-LLM call failed: {e}")

        llm_correct = answers_match(reference, llm_run1) if llm_run1 else False
        changed_on_repetition = (
            _normalize_answer(llm_run1) != _normalize_answer(llm_run2)
            if llm_run1 and llm_run2 else None
        )

        rows.append({
            "ID": qid,
            "Level": level,
            "Query": query,
            "Reference answer": reference,
            "Studify answer": studify_answer,
            "Studify correct": studify_correct,
            "LLM answer (run 1)": llm_run1,
            "LLM answer (run 2)": llm_run2,
            "LLM correct": llm_correct,
            "LLM changed on repetition": changed_on_repetition,
        })
        time.sleep(3)

    with open("table_4_17_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    manual_check_needed = [r for r in rows if r["Studify correct"] == "NEEDS_MANUAL_CHECK"
                           or r["LLM correct"] == "NEEDS_MANUAL_CHECK"]
    if manual_check_needed:
        print(f"\n*** {len(manual_check_needed)} rows need manual verification "
              f"(automated symbolic comparison was not confident) -- see "
              f"table_4_17_results.csv, IDs: {[r['ID'] for r in manual_check_needed]} ***")

    print("\n=== TABLE 4.17: FINAL-ANSWER ACCURACY ===")
    for level in ["Simple", "Intermediate", "Multi-step", "All"]:
        subset = rows if level == "All" else [r for r in rows if r["Level"] == level]
        if not subset:
            continue
        studify_ok = sum(1 for r in subset if r["Studify correct"] is True)
        llm_ok = sum(1 for r in subset if r["LLM correct"] is True)
        changed = sum(1 for r in subset if r["LLM changed on repetition"] is True)
        print(f"{level}: n={len(subset)} Studify correct={studify_ok} "
              f"LLM correct={llm_ok} LLM changed on repetition={changed}")

    print("\nWrote table_4_17_results.csv")
    return rows


def load_results_from_csv(path="pipeline_results.csv"):
    """
    Loads a previously-written pipeline_results.csv (from an earlier
    collect_pipeline_runs() run) so explanation-quality scoring can be
    (re)done WITHOUT calling /solve again. CSV values are all strings,
    so "success" is converted back to a real bool -- otherwise the
    string "False" is truthy in Python and every row would look
    successful to run_explanation_quality()'s checks.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found. Run with --stage collect first (or --stage all) "
            f"to generate it before scoring."
        )
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["success"] = (r.get("success") == "True")
    print(f"Loaded {len(rows)} previously-collected results from {path} "
          f"(no new /solve calls made).")
    return rows


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEST_BANK_PATH = os.path.join(SCRIPT_DIR, "test_bank_4_6.csv")


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=["all", "collect", "quality", "table417"],
        default="all",
        help=(
            "all: run everything from scratch (original behavior, ~30 fresh "
            "/solve calls plus quality scoring plus Table 4.17). "
            "collect: only Table 4.14 latency + write pipeline_results.csv "
            "(no quality scoring). "
            "quality: (re)score explanation quality from an EXISTING "
            "pipeline_results.csv -- makes NO new /solve calls, only "
            "OpenRouter calls. Use this if you already have real "
            "pipeline_results.csv from a prior run and just need Tables "
            "4.12/4.13. "
            "table417: run only the Table 4.17 comparison against the "
            "38-item bank -- does not touch the 30-query interpretation "
            "bank or re-collect latency data at all."
        ),
    )
    parser.add_argument(
        "--results-csv", default="pipeline_results.csv",
        help="Path to read/write pipeline_results.csv (default: ./pipeline_results.csv)",
    )
    parser.add_argument(
        "--test-bank-csv", default=DEFAULT_TEST_BANK_PATH,
        help=f"Path to the 38-item test bank CSV (default: {DEFAULT_TEST_BANK_PATH}, "
             f"i.e. next to this script)",
    )
    args = parser.parse_args()

    if args.stage == "all":
        results = collect_pipeline_runs()
        run_latency(results)
        scored = run_explanation_quality(results)
        write_csv(results, scored, path=args.results_csv)
        run_table_4_17(test_bank_csv_path=args.test_bank_csv)

    elif args.stage == "collect":
        results = collect_pipeline_runs()
        run_latency(results)
        write_csv(results, scored=[], path=args.results_csv)
        print("\nRan --stage collect only. Rerun with --stage quality once "
              "OPENROUTER_API_KEY is set, to score these same explanations "
              "without spending any more Studify/explainer quota.")

    elif args.stage == "quality":
        results = load_results_from_csv(args.results_csv)
        scored = run_explanation_quality(results)
        write_csv(results, scored, path=args.results_csv)

    elif args.stage == "table417":
        run_table_4_17(test_bank_csv_path=args.test_bank_csv)
