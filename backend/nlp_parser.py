import json
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL_NAME = "gemini-3.5-flash-lite"

SYSTEM_PROMPT = """
You are a mathematical expression parser for an engineering academic assistant.

Your ONLY job is to extract structured information from a natural language math query.
You must respond with ONLY a valid JSON object — no explanation, no markdown, no extra text.

The JSON must have these exact keys:
- "operation": one of ["derivative", "indefinite_integral", "definite_integral",
                        "limit", "solve", "simplify", "taylor", "laplace",
                        "inverse_laplace", "unknown"]
- "expression": the mathematical expression as a SymPy-compatible string
                (use ** for powers, * for multiplication)
- "variable": the variable of interest as a string (default "x")
- "lower": lower limit as string if definite integral, else null
- "upper": upper limit as string if definite integral, else null
- "point": the point for limits or taylor series as string, else null
- "order": integer order for taylor series, else null

SymPy formatting rules you must follow:
- Use ** for powers (x**2 not x^2)
- Use * for multiplication (3*x not 3x)
- Use sp.sin, sp.cos, sp.exp style names: sin(x), cos(x), exp(x), log(x)
- Use oo for infinity

Examples:
Input: "differentiate x squared plus 3x"
Output: {"operation": "derivative", "expression": "x**2 + 3*x", "variable": "x",
         "lower": null, "upper": null, "point": null, "order": null}

Input: "integrate x cubed from 0 to 5"
Output: {"operation": "definite_integral", "expression": "x**3", "variable": "x",
         "lower": "0", "upper": "5", "point": null, "order": null}

Input: "find the laplace transform of t squared"
Output: {"operation": "laplace", "expression": "t**2", "variable": "t",
         "lower": null, "upper": null, "point": null, "order": null}
"""


def parse_query(user_query: str) -> dict:
    """
    Takes a natural language math query and returns a structured dictionary.
    This is the NLP Interpretation Layer of the neurosymbolic pipeline.
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_query,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=256,
            ),
        )

        raw = response.text.strip()
        # Strip markdown code fences if Gemini wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        # Parse the JSON response
        parsed = json.loads(raw)

        # Validate required keys are present
        required_keys = ["operation", "expression", "variable",
                         "lower", "upper", "point", "order"]
        for key in required_keys:
            if key not in parsed:
                parsed[key] = None

        return parsed

    except json.JSONDecodeError:
        return {
            "operation": "unknown",
            "expression": None,
            "variable": "x",
            "lower": None,
            "upper": None,
            "point": None,
            "order": None,
            "error": "Could not parse your query into a math expression."
        }
    except Exception as e:
        return {
            "operation": "unknown",
            "expression": None,
            "variable": "x",
            "lower": None,
            "upper": None,
            "point": None,
            "order": None,
            "error": f"Parser error: {str(e)}"
        }


# ── Self-test ──

if __name__ == "__main__":
    tests = [
        "find the derivative of x cubed plus 2x",
        "integrate sin(x) from 0 to pi",
        "what is the limit of sin(x)/x as x approaches 0",
        "solve x squared minus 9 equals zero",
        "laplace transform of e to the power negative 2t",
    ]

    for query in tests:
        print(f"\nQuery  : {query}")
        result = parse_query(query)
        print(f"Parsed : {result}")
