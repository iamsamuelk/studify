import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL_NAME = "gemini-2.5-pro"

SYSTEM_PROMPT = """
You are Studify, a patient and thorough engineering mathematics tutor for
undergraduate students in Nigeria and beyond.

You will be given:
1. The student's original question
2. The verified symbolic computation result

Your job is to write a clear, step-by-step explanation of HOW that
result was reached.

STRICT RULES:
- You must treat the provided result as the ground truth.
  Never recalculate or second-guess it.
- Write your explanation as numbered steps.
- At each step, name the rule or principle being applied
  (e.g., Power Rule, Chain Rule, Integration by Parts).
- Use simple, clear language suitable for an undergraduate student.
- After the steps, write a brief conceptual note explaining WHY
  this type of operation matters in engineering.
- End every response with a clearly labelled Final Answer.

FORMAT:
**Step 1:** [What you do and why]
**Step 2:** [What you do and why]
...
**Conceptual Note:** [Why this matters in engineering]
**Final Answer:** [Restate the result cleanly]
"""


def generate_explanation(user_query: str, operation: str,
                         expression: str, result: str) -> str:
    """
    Generate a pedagogical step-by-step explanation.
    Conditioned on the original query AND the verified symbolic result.
    This is the G function in S(I) = G(I, T(E)).
    """
    try:
        user_message = f"""
Student's question: {user_query}

Operation performed: {operation}
Expression: {expression}
Verified result from symbolic engine: {result}

Please explain step-by-step how this result was obtained.
"""

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=4096,
            ),
        )

        return response.text.strip()

    except Exception as e:
        return f"Explanation error: {str(e)}"


# ── Self-test ──

if __name__ == "__main__":
    tests = [
        {
            "query": "find the derivative of x cubed plus 2x",
            "operation": "derivative",
            "expression": "x**3 + 2*x",
            "result": "3*x**2 + 2"
        },
        {
            "query": "integrate sin(x) from 0 to pi",
            "operation": "definite_integral",
            "expression": "sin(x)",
            "result": "2"
        },
        {
            "query": "laplace transform of e to the power negative 2t",
            "operation": "laplace",
            "expression": "exp(-2*t)",
            "result": "1/(s + 2)"
        }
    ]

    for test in tests:
        print(f"\n{'='*60}")
        print(f"Query: {test['query']}")
        print(f"{'='*60}")
        explanation = generate_explanation(
            test["query"],
            test["operation"],
            test["expression"],
            test["result"]
        )
        print(explanation)
