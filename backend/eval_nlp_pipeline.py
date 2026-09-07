"""
eval_nlp_pipeline.py

Runs the Table 4.9 test bank (30 natural-language queries) against the LIVE
Studify /solve endpoint with skip_explanation=True, checks the NLP
interpretation layer's output against the expected operation/expression/
parameters, repeats each query 3x to check consistency, and writes real
results to nlp_results.csv.

=====================================================================
WHY skip_explanation=True (as of the v1.5 main.py patch):
=====================================================================
Real quota check (2026-09-07, Google AI Studio dashboard):
  gemini-3.5-flash-lite (parser)   : RPM 15, RPD 500,  TPM 250K
  gemini-3.1-flash-lite (fallback) : RPM 15, RPD 500,  TPM 250K
  gemini-3.6-flash (explainer)     : RPM  5, RPD  20,  TPM 250K  <-- tight
  gemini-3.8-flash (fallback)      : RPM  5, RPD  20,  TPM 250K  <-- tight

This eval only checks operation/expression/parameters -- it never needed
the explanation text. Previously every /solve call triggered the
explainer too, so a 90-call run (30 queries x 3) could burn most or all
of the explainer's 20-40/day combined budget just to test parsing. Since
backend/main.py now accepts "skip_explanation": true, this script uses
it, so this eval no longer touches the explainer's quota at all --
leaving that budget free for the separate explanation-quality run
(Tables 4.12/4.13) and the end-to-end latency run (Table 4.14), which
DO need real explanations and should be run and budgeted separately
(see eval_pipeline_latency.py).

With the explainer out of the picture, the parser's own budget (RPM 15,
RPD 500) comfortably covers all 90 calls; this script still throttles
and retries on 429 as a safety net, not because it's expected to trigger.

BEFORE RUNNING:
- Confirm the deployed main.py accepts "skip_explanation" in the request
  body (v1.5 or later). If it's an older deployment, this field is
  silently ignored by FastAPI/Pydantic and every call will still invoke
  the explainer -- check one response manually first
  ("explanation" should be null in the JSON when skip_explanation=true).

Usage:
    pip install requests --break-system-packages
    python eval_nlp_pipeline.py
"""

import csv
import time
import requests

BASE_URL = "https://studify.quikdb.net"
SOLVE_ENDPOINT = "/solve"
REQUEST_PAYLOAD_KEY = "query"
N_RUNS = 3

# Parser quota is RPM 15 / RPD 500 -- 3s spacing keeps us at ~20/min,
# a bit over 15 in theory but our 429 retry below absorbs any overshoot
# without risking the tight explainer budget (which isn't touched here).
DELAY_BETWEEN_CALLS_S = 3.0
MAX_RETRIES_ON_429 = 4
BASE_BACKOFF_S = 15.0

TEST_BANK = [
    ("Q01", "Simple", "Differentiate x cubed plus 3x squared plus 2x",
     "derivative", "x**3 + 3*x**2 + 2*x", {}),
    ("Q02", "Simple", "What is the derivative of sin(x)?",
     "derivative", "sin(x)", {}),
    ("Q03", "Simple", "Integrate 2x",
     "indefinite_integral", "2*x", {}),
    ("Q04", "Simple", "Find the integral of cos x dx",
     "indefinite_integral", "cos(x)", {}),
    ("Q05", "Simple", "Integrate x squared from 0 to 3",
     "definite_integral", "x**2", {"lower": "0", "upper": "3"}),
    ("Q06", "Simple", "Solve x squared minus 9 equals zero",
     "solve", "x**2 - 9", {}),
    ("Q07", "Simple", "Simplify (x^2 - 1)/(x - 1)",
     "simplify", "(x**2 - 1)/(x - 1)", {}),
    ("Q08", "Simple", "Laplace transform of 1",
     "laplace", "1", {}),
    ("Q09", "Simple", "Find the limit of sin(x)/x as x approaches 0",
     "limit", "sin(x)/x", {"point": "0"}),
    ("Q10", "Simple", "Inverse Laplace transform of 1/s",
     "inverse_laplace", "1/s", {}),
    ("Q11", "Intermediate", "Differentiate x squared times e to the x",
     "derivative", "x**2*exp(x)", {}),
    ("Q12", "Intermediate", "d/dx of sin(x^2)",
     "derivative", "sin(x**2)", {}),
    ("Q13", "Intermediate", "Integrate sin(x) from 0 to pi",
     "definite_integral", "sin(x)", {"lower": "0", "upper": "pi"}),
    ("Q14", "Intermediate", "Evaluate the integral of e^(-x) between 0 and infinity",
     "definite_integral", "exp(-x)", {"lower": "0", "upper": "oo"}),
    ("Q15", "Intermediate", "Integrate x e^x with respect to x",
     "indefinite_integral", "x*exp(x)", {}),
    ("Q16", "Intermediate", "limit of (1 + 1/x)^x as x tends to infinity",
     "limit", "(1 + 1/x)**x", {"point": "oo"}),
    ("Q17", "Intermediate", "Find the roots of x^2 + 4x + 4",
     "solve", "x**2 + 4*x + 4", {}),
    ("Q18", "Intermediate", "Taylor series of sin(x) about 0",
     "taylor", "sin(x)", {"point": "0"}),
    ("Q19", "Intermediate", "Laplace transform of e to the power negative 2t",
     "laplace", "exp(-2*t)", {}),
    ("Q20", "Intermediate", "Find the Laplace transform of t squared",
     "laplace", "t**2", {}),
    ("Q21", "Intermediate", "Inverse Laplace of 1 over s plus 2",
     "inverse_laplace", "1/(s + 2)", {}),
    ("Q22", "Intermediate", "Simplify sin squared x plus cos squared x",
     "simplify", "sin(x)**2 + cos(x)**2", {}),
    ("Q23", "Multi-step", "Differentiate ln(x) divided by x",
     "derivative", "log(x)/x", {}),
    ("Q24", "Multi-step", "Differentiate e^(-2t) cos(3t) with respect to t",
     "derivative", "exp(-2*t)*cos(3*t)", {}),
    ("Q25", "Multi-step", "Integrate 1/(x^2 - 1) using partial fractions",
     "indefinite_integral", "1/(x**2 - 1)", {}),
    ("Q26", "Multi-step", "Integrate x sin x from 0 to pi",
     "definite_integral", "x*sin(x)", {"lower": "0", "upper": "pi"}),
    ("Q27", "Multi-step", "Solve the cubic x^3 - 6x^2 + 11x - 6 = 0",
     "solve", "x**3 - 6*x**2 + 11*x - 6", {}),
    ("Q28", "Multi-step", "Expand ln(1+x) as a Taylor series about 0 up to order 5",
     "taylor", "log(1 + x)", {"point": "0", "order": "5"}),
    ("Q29", "Multi-step", "Laplace transform of t e^(-t)",
     "laplace", "t*exp(-t)", {}),
    ("Q30", "Multi-step", "Find the inverse Laplace transform of 1/(s^2 + 3s + 2)",
     "inverse_laplace", "1/(s**2 + 3*s + 2)", {}),
]

OP_LABELS = {
    "derivative": "derivative",
    "indefinite_integral": "indefinite integral",
    "definite_integral": "definite integral",
    "limit": "limit",
    "solve": "solve",
    "simplify": "simplify",
    "taylor": "taylor",
    "laplace": "laplace",
    "inverse_laplace": "inverse laplace",
}


def normalize(s):
    if s is None:
        return None
    return str(s).replace(" ", "").lower()


def is_rate_limit_error(exc_or_payload):
    text = str(exc_or_payload)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower()


def call_solve_with_retry(query):
    url = BASE_URL.rstrip("/") + SOLVE_ENDPOINT
    last_error = None

    for attempt in range(MAX_RETRIES_ON_429 + 1):
        t0 = time.perf_counter()
        try:
            resp = requests.post(
                url,
                json={REQUEST_PAYLOAD_KEY: query, "skip_explanation": True},
                timeout=90,
            )
            elapsed = time.perf_counter() - t0

            if resp.status_code == 429:
                last_error = f"HTTP 429: {resp.text[:300]}"
                if attempt < MAX_RETRIES_ON_429:
                    backoff = BASE_BACKOFF_S * (2 ** attempt)
                    print(f"    HTTP 429, retrying in {backoff:.0f}s (attempt {attempt+1}/{MAX_RETRIES_ON_429})")
                    time.sleep(backoff)
                    continue
                return None, elapsed, last_error

            resp.raise_for_status()
            data = resp.json()

            if data.get("success") is False and is_rate_limit_error(data.get("error")):
                last_error = data.get("error")
                if attempt < MAX_RETRIES_ON_429:
                    backoff = BASE_BACKOFF_S * (2 ** attempt)
                    print(f"    Quota error in payload, retrying in {backoff:.0f}s (attempt {attempt+1}/{MAX_RETRIES_ON_429})")
                    time.sleep(backoff)
                    continue
                return data, elapsed, last_error

            return data, elapsed, None

        except requests.exceptions.RequestException as e:
            elapsed = time.perf_counter() - t0
            last_error = str(e)
            if is_rate_limit_error(e) and attempt < MAX_RETRIES_ON_429:
                backoff = BASE_BACKOFF_S * (2 ** attempt)
                print(f"    Request error (possible 429), retrying in {backoff:.0f}s (attempt {attempt+1}/{MAX_RETRIES_ON_429})")
                time.sleep(backoff)
                continue
            return None, elapsed, last_error

    return None, None, last_error


def check_parameters(data, expected_params):
    if not expected_params:
        return True
    for key, expected_val in expected_params.items():
        got_val = data.get(key)
        if key == "order":
            try:
                if int(got_val) != int(expected_val):
                    return False
            except (TypeError, ValueError):
                return False
        else:
            if normalize(got_val) != normalize(expected_val):
                return False
    return True


def run_eval():
    rows = []
    total_queries = len(TEST_BANK)

    for idx, (qid, level, query, exp_op, exp_expr, exp_params) in enumerate(TEST_BANK, start=1):
        print(f"[{qid}] ({idx}/{total_queries}) {query}")
        run_data = []
        run_errors = []
        parse_times = []

        for run_i in range(N_RUNS):
            data, elapsed, error = call_solve_with_retry(query)
            run_data.append(data)
            run_errors.append(error)
            parse_times.append(elapsed)
            if error:
                print(f"  run {run_i + 1}: FAILED - {error[:150]}")
            time.sleep(DELAY_BETWEEN_CALLS_S)

        first = run_data[0] or {}
        got_op = first.get("operation")
        got_expr = first.get("expression")

        exp_op_label = OP_LABELS.get(exp_op, exp_op)
        operation_correct = normalize(got_op) in (normalize(exp_op_label), normalize(exp_op))
        expression_correct = normalize(got_expr) == normalize(exp_expr)
        parameters_correct = check_parameters(first, exp_params) if first.get("success") else False

        signature = lambda d: (d.get("operation"), d.get("expression")) if d else None
        consistent = len({signature(d) for d in run_data}) == 1

        valid_times = [t for t in parse_times if t is not None]
        mean_parse_time = round(sum(valid_times) / len(valid_times), 3) if valid_times else None

        # Sanity check: explanation should be null since skip_explanation=True.
        # If it's NOT null, the deployed main.py doesn't support the flag yet.
        explanation_leaked = bool(first.get("explanation"))

        rows.append({
            "ID": qid,
            "Level": level,
            "Query": query,
            "Expected operation": exp_op_label,
            "Expected expression": exp_expr,
            "Got operation": got_op,
            "Got expression": got_expr,
            "Got success": first.get("success"),
            "Got error": first.get("error") or run_errors[0],
            "Operation correct": operation_correct,
            "Expression correct": expression_correct,
            "Parameters correct": parameters_correct,
            "Consistent (3 runs)": consistent,
            "Mean parse time (s)": mean_parse_time,
            "skip_explanation honored": not explanation_leaked,
        })

        fieldnames = list(rows[0].keys())
        with open("nlp_results.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    if any(not r["skip_explanation honored"] for r in rows):
        print("\n*** WARNING: explanation text came back despite skip_explanation=True. ***")
        print("*** The deployed main.py may be an older version without the flag -- ***")
        print("*** this run likely still consumed explainer quota. Redeploy and rerun. ***\n")

    def pct(vals):
        vals = [v for v in vals if v is not None]
        return round(100 * sum(bool(v) for v in vals) / len(vals), 1) if vals else None

    for level in ["Simple", "Intermediate", "Multi-step", "ALL"]:
        subset = rows if level == "ALL" else [r for r in rows if r["Level"] == level]
        if not subset:
            continue
        print(f"\n--- {level} (n={len(subset)}) ---")
        print("Operation accuracy:", pct([r["Operation correct"] for r in subset]))
        print("Expression accuracy:", pct([r["Expression correct"] for r in subset]))
        print("Parameter accuracy:", pct([r["Parameters correct"] for r in subset]))
        print("Full-parse accuracy:", pct([r["Operation correct"] and r["Expression correct"] for r in subset]))
        print("Consistency:", pct([r["Consistent (3 runs)"] for r in subset]))
        times = [r["Mean parse time (s)"] for r in subset if r["Mean parse time (s)"] is not None]
        print("Mean parse time (s):", round(sum(times) / len(times), 3) if times else None)

    print("\nWrote nlp_results.csv")


if __name__ == "__main__":
    run_eval()
