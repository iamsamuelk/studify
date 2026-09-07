from supabase import create_client
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.pipeline import run_pipeline
import os
import sys
sys.path.append(os.path.dirname(__file__))


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
