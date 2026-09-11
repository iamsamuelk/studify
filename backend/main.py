from supabase import create_client
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.pipeline import run_pipeline
from backend.vision_parser import extract_math_from_image
import os
import sys
import time
sys.path.append(os.path.dirname(__file__))

# ── Image upload constraints ────────────────────────────────────────────────

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


# ── Supabase ─────────────────────────────────────────────────────────────────

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY"))

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Studify — AI Engineering Mathematics Tutor",
    description="A neurosymbolic AI academic assistant for undergraduate engineering mathematics.",
    version="2.0.0"
)

# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Database ─────────────────────────────────────────────────────────────────

def log_query(user_query: str, result: dict):
    parsed = result.get("parsed") or {}
    supabase.table("queries").insert({
        "user_query": user_query,
        "operation": parsed.get("operation"),
        "expression": parsed.get("expression"),
        "symbolic_result": result.get("symbolic_result"),
        "symbolic_result_latex": result.get("symbolic_result_latex"),
        "explanation": result.get("explanation"),
        "success": bool(result.get("success", False)),
    }).execute()


# ── Schemas ──────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    skip_explanation: bool = False
    # ^ For automated evaluation of the interpretation layer only (e.g.
    # Table 4.9 NLP accuracy testing). When True, the explainer model is
    # never called, so evaluation traffic doesn't consume the explainer's
    # daily quota (gemini-3.6-flash: RPD 20) or pollute /history and
    # /stats with synthetic queries. Defaults to False so normal frontend
    # usage is unaffected.


class QueryResponse(BaseModel):
    success: bool
    query: str
    operation: str | None = None
    expression: str | None = None
    variable: str | None = None
    lower: str | None = None
    upper: str | None = None
    point: str | None = None
    order: int | None = None
    symbolic_result: str | None = None
    symbolic_result_latex: str | None = None
    explanation: str | None = None
    error: str | None = None
    interpretation_time_s: float | None = None
    symbolic_time_s: float | None = None
    explanation_time_s: float | None = None


class ImageQueryResponse(QueryResponse):
    extracted_query: str | None = None
    # ^ The plain-text query the vision layer read off the image, shown
    # back to the user for confirmation/editing before it's treated as
    # ground truth downstream.
    vision_time_s: float | None = None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "online",
        "system": "Studify",
        "version": "2.0.0"
    }


@app.post("/solve", response_model=QueryResponse)
def solve(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    result = run_pipeline(request.query, skip_explanation=request.skip_explanation)

    if not request.skip_explanation:
        log_query(request.query, result)

    parsed = result.get("parsed") or {}
    return QueryResponse(
        success=result["success"],
        query=result["query"],
        operation=parsed.get("operation"),
        expression=parsed.get("expression"),
        variable=parsed.get("variable"),
        lower=parsed.get("lower"),
        upper=parsed.get("upper"),
        point=parsed.get("point"),
        order=int(parsed["order"]) if parsed.get("order") not in (None, "") else None,
        symbolic_result=result.get("symbolic_result"),
        symbolic_result_latex=result.get("symbolic_result_latex"),
        explanation=result.get("explanation"),
        error=result.get("error"),
        interpretation_time_s=result.get("interpretation_time_s"),
        symbolic_time_s=result.get("symbolic_time_s"),
        explanation_time_s=result.get("explanation_time_s"),
    )


@app.post("/solve-image", response_model=ImageQueryResponse)
async def solve_image(
    file: UploadFile = File(...),
    skip_explanation: bool = Form(False),
):
    if file.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{file.content_type}'. "
                   f"Use JPEG, PNG, or WEBP.",
        )

    image_bytes = await file.read()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.",
        )

    t0 = time.perf_counter()
    vision_result = extract_math_from_image(image_bytes, mime_type=file.content_type)
    vision_time_s = time.perf_counter() - t0

    if not vision_result["success"]:
        return ImageQueryResponse(
            success=False,
            query="",
            extracted_query=None,
            error=vision_result["error"],
            vision_time_s=vision_time_s,
        )

    extracted_query = vision_result["extracted_query"]

    # Reuse the existing text pipeline unchanged -- vision is purely an
    # additional entry point feeding the same S(I) = G(I, T(E)) pipeline.
    result = run_pipeline(extracted_query, skip_explanation=skip_explanation)

    if not skip_explanation:
        log_query(extracted_query, result)

    parsed = result.get("parsed") or {}
    return ImageQueryResponse(
        success=result["success"],
        query=result["query"],
        extracted_query=extracted_query,
        operation=parsed.get("operation"),
        expression=parsed.get("expression"),
        variable=parsed.get("variable"),
        lower=parsed.get("lower"),
        upper=parsed.get("upper"),
        point=parsed.get("point"),
        order=int(parsed["order"]) if parsed.get("order") not in (None, "") else None,
        symbolic_result=result.get("symbolic_result"),
        symbolic_result_latex=result.get("symbolic_result_latex"),
        explanation=result.get("explanation"),
        error=result.get("error"),
        interpretation_time_s=result.get("interpretation_time_s"),
        symbolic_time_s=result.get("symbolic_time_s"),
        explanation_time_s=result.get("explanation_time_s"),
        vision_time_s=vision_time_s,
    )


@app.get("/history")
def get_history(limit: int = 20):
    response = supabase.table("queries").select("*").order("id", desc=True).limit(limit).execute()
    rows = response.data or []
    return {
        "history": [
            {
                "id": row["id"],
                "timestamp": row.get("created_at", ""),
                "query": row["user_query"],
                "operation": row.get("operation"),
                "expression": row.get("expression"),
                "symbolic_result": row.get("symbolic_result"),
                "symbolic_result_latex": row.get("symbolic_result_latex"),
                "explanation": row.get("explanation"),
                "success": row.get("success", False)
            }
            for row in rows
        ]
    }


@app.get("/stats")
def get_stats():
    total_res = supabase.table("queries").select("*", count="exact").execute()
    total = total_res.count or 0

    success_res = supabase.table("queries").select("*", count="exact").eq("success", True).execute()
    successful = success_res.count or 0

    ops_res = supabase.table("queries").select("operation").not_.is_("operation", "null").execute()
    op_counts = {}
    for row in (ops_res.data or []):
        op = row.get("operation")
        if op:
            op_counts[op] = op_counts.get(op, 0) + 1

    by_operation = sorted(
        [{"operation": k, "count": v} for k, v in op_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )

    return {
        "total_queries": total,
        "successful": successful,
        "failed": total - successful,
        "success_rate": round(successful / total * 100, 2) if total > 0 else 0,
        "by_operation": by_operation
    }


# ── Serve Frontend ───────────────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/{path:path}")
def serve_frontend(path: str):
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
