import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Vision extraction shares the NLP parser's high-quota model, NOT the
# explainer's gemini-3.8-flash (RPD-20). Extraction is a per-image call
# on top of the normal parse, so it must stay off the tight-quota model.
PRIMARY_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.1-flash-lite"


def _is_quota_error(exc) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()


def _is_retryable_error(exc) -> bool:
    """
    Broader than _is_quota_error: also covers transient server-side
    overload (503 UNAVAILABLE), which Gemini returns when a model is
    getting hammered by demand -- unrelated to OUR quota, but just as
    fixable by falling back to the secondary model.
    """
    text = str(exc)
    if _is_quota_error(exc):
        return True
    return "503" in text or "UNAVAILABLE" in text or "overloaded" in text.lower()


def _generate_with_fallback(contents, config):
    """
    Same fallback pattern as nlp_parser._generate_with_fallback: try
    PRIMARY_MODEL, retry once on FALLBACK_MODEL on a quota/rate-limit
    error OR a transient 503 overload. No persistent fallback state --
    next call starts on PRIMARY again.
    """
    try:
        response = client.models.generate_content(
            model=PRIMARY_MODEL, contents=contents, config=config,
        )
        return response, PRIMARY_MODEL
    except Exception as e:
        if not _is_retryable_error(e):
            raise
        print(f"[vision_parser] {PRIMARY_MODEL} unavailable/quota hit, falling back to {FALLBACK_MODEL}")
        response = client.models.generate_content(
            model=FALLBACK_MODEL, contents=contents, config=config,
        )
        return response, FALLBACK_MODEL


SYSTEM_PROMPT = """
You are a math problem transcriber for an engineering academic assistant.

You will be shown an image containing a mathematical problem (printed or
handwritten). Your ONLY job is to transcribe it into a single plain-text
query that a downstream NLP parser can interpret.

Rules:
- Output ONLY the transcribed query as plain text. No markdown, no
  preamble, no explanation, no code fences.
- Phrase it as a natural language math instruction, e.g.
  "differentiate x^2 + 3x" or "integrate sin(x) from 0 to pi" or
  "solve x^2 - 9 = 0".
- Use ^ for powers and standard math notation (not SymPy syntax --
  the downstream parser handles that conversion).
- If the image contains multiple problems, transcribe ONLY the first one.
- If handwriting is ambiguous, use your best mathematical judgement but
  do not guess wildly -- prefer the most standard interpretation.
- If the image contains NO legible math problem, output exactly:
  NO_MATH_FOUND
"""


def extract_math_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Takes raw image bytes and returns a dict with the transcribed plain-
    text query, ready to be handed to nlp_parser.parse_query (i.e. the
    same entry point the text pipeline already uses). Mirrors the
    error-shape conventions of nlp_parser.parse_query.
    """
    try:
        response, model_used = _generate_with_fallback(
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                SYSTEM_PROMPT,
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=256,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        text = (response.text or "").strip()

        if not text or text == "NO_MATH_FOUND":
            return {
                "success": False,
                "extracted_query": None,
                "error": "No legible math problem was found in the image.",
                "_model_used": model_used,
            }

        return {
            "success": True,
            "extracted_query": text,
            "error": None,
            "_model_used": model_used,
        }

    except Exception as e:
        return {
            "success": False,
            "extracted_query": None,
            "error": f"Vision extraction error: {str(e)}",
            "_model_used": None,
        }


# ── Self-test ──

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m backend.vision_parser <path_to_image>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "rb") as f:
        img_bytes = f.read()

    ext = os.path.splitext(path)[1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(
        ext.lstrip("."), "image/jpeg"
    )

    result = extract_math_from_image(img_bytes, mime_type=mime)
    print(result)
