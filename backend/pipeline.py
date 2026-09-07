import time
import sympy as sp
from backend.nlp_parser import parse_query
from backend.math_engine import (
    calculate_derivative,
    calculate_indefinite_integral,
    calculate_definite_integral,
    calculate_limit,
    solve_equation,
    simplify_expression,
    taylor_series,
    laplace_transform,
    inverse_laplace_transform,
)
from backend.explainer import generate_explanation


# Maps operation strings from the NLP parser to math_engine functions
OPERATION_MAP = {
    "derivative": lambda p: calculate_derivative(
        p["expression"], p["variable"] or "x"
    ),
    "indefinite_integral": lambda p: calculate_indefinite_integral(
        p["expression"], p["variable"] or "x"
    ),
    "definite_integral": lambda p: calculate_definite_integral(
        p["expression"],
        p["variable"] or "x",
        p["lower"] or "0",
        p["upper"] or "1",
    ),
    "limit": lambda p: calculate_limit(
        p["expression"],
        p["variable"] or "x",
        p["point"] or "0",
    ),
    "solve": lambda p: solve_equation(
        p["expression"], p["variable"] or "x"
    ),
    "simplify": lambda p: simplify_expression(p["expression"]),
    "taylor": lambda p: taylor_series(
        p["expression"],
        p["variable"] or "x",
        p["point"] or "0",
        int(p["order"]) if p["order"] else 5,
    ),
    "laplace": lambda p: laplace_transform(p["expression"]),
    "inverse_laplace": lambda p: inverse_laplace_transform(p["expression"]),
}


def run_pipeline(user_query: str, skip_explanation: bool = False) -> dict:
    """
    The full neurosymbolic pipeline: S(I) = G(I, T(E))

    Step 1: Receive natural language input I
    Step 2: Validate input is not empty
    Step 3: Parse I → structured representation (operation, expression)
    Step 4: Validate parsing succeeded
    Step 5: Route to symbolic engine → compute T(E)
    Step 6: Validate symbolic result
    Step 7: Generate explanation G conditioned on I and T(E)
             (skipped if skip_explanation=True -- e.g. for interpretation-
             only evaluation, where the explainer model's quota should be
             reserved for genuine explanation-quality testing, Tables
             4.12/4.13, rather than spent on every interpretation check)
    Step 8: Return structured response
    """

    # Step 1 & 2 — Receive and validate input
    if not user_query or not user_query.strip():
        return {
            "success": False,
            "error": "Input cannot be empty.",
            "query": user_query,
            "parsed": None,
            "symbolic_result": None,
            "explanation": None,
            "interpretation_time_s": None,
            "symbolic_time_s": None,
            "explanation_time_s": None,
        }

    # Step 3 — NLP Parsing: I → {operation, expression, ...}
    t0 = time.perf_counter()
    parsed = parse_query(user_query)
    interpretation_time_s = time.perf_counter() - t0

    # Step 4 — Validate parsing result
    if parsed.get("operation") == "unknown" or not parsed.get("expression"):
        return {
            "success": False,
            "error": parsed.get(
                "error",
                "Could not understand your query. "
                "Please rephrase your math question."
            ),
            "query": user_query,
            "parsed": parsed,
            "symbolic_result": None,
            "explanation": None,
            "interpretation_time_s": interpretation_time_s,
            "symbolic_time_s": None,
            "explanation_time_s": None,
        }

    operation = parsed["operation"]

    # Step 5 — Symbolic computation: T(E)
    if operation not in OPERATION_MAP:
        return {
            "success": False,
            "error": f"Operation '{operation}' is not supported yet.",
            "query": user_query,
            "parsed": parsed,
            "symbolic_result": None,
            "explanation": None,
            "interpretation_time_s": interpretation_time_s,
            "symbolic_time_s": None,
            "explanation_time_s": None,
        }

    t0 = time.perf_counter()
    symbolic_result = OPERATION_MAP[operation](parsed)
    symbolic_time_s = time.perf_counter() - t0

    # Convert symbolic result to LaTeX for frontend rendering
    try:
        symbolic_result_latex = sp.latex(sp.sympify(str(symbolic_result)))
    except Exception:
        symbolic_result_latex = str(symbolic_result)

    # Step 6 — Validate symbolic result
    if isinstance(symbolic_result, str) and symbolic_result.startswith("Error"):
        return {
            "success": False,
            "error": symbolic_result,
            "query": user_query,
            "parsed": parsed,
            "symbolic_result": None,
            "explanation": None,
            "interpretation_time_s": interpretation_time_s,
            "symbolic_time_s": symbolic_time_s,
            "explanation_time_s": None,
        }

    # Step 7 — Generate explanation: G(I, T(E))
    explanation_time_s = None
    if skip_explanation:
        explanation = None
    else:
        t0 = time.perf_counter()
        explanation = generate_explanation(
            user_query=user_query,
            operation=operation,
            expression=parsed["expression"],
            result=str(symbolic_result),
        )
        explanation_time_s = time.perf_counter() - t0

    # Step 8 — Return full structured response
    return {
        "success": True,
        "error": None,
        "query": user_query,
        "parsed": parsed,
        "symbolic_result": str(symbolic_result),
        "symbolic_result_latex": symbolic_result_latex,
        "explanation": explanation,
        "interpretation_time_s": interpretation_time_s,
        "symbolic_time_s": symbolic_time_s,
        "explanation_time_s": explanation_time_s,
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    queries = [
        "find the derivative of x cubed plus 3x squared",
        "what is the definite integral of x squared from 1 to 4",
        "find the laplace transform of sin(t)",
    ]

    for q in queries:
        print(f"\n{'='*60}")
        print(f"INPUT : {q}")
        print(f"{'='*60}")
        result = run_pipeline(q)
        if result["success"]:
            print(f"PARSED        : {result['parsed']}")
            print(f"SYMBOLIC RESULT: {result['symbolic_result']}")
            print(f"\nEXPLANATION:\n{result['explanation']}")
        else:
            print(f"ERROR: {result['error']}")