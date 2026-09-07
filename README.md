# Studify 🎓

An AI-powered engineering mathematics tutor for undergraduate students.
Ask any calculus, mechanics, or control systems question in plain English
and get a symbolic result plus a step-by-step explanation.

## Live Demo
[https://studify.quikdb.net](https://studify.quikdb.net)

## Features
- Natural language math queries
- Symbolic computation via SymPy
- Step-by-step AI explanations powered by Google Gemini
- Query history saved to Supabase
- Supports: derivatives, integrals, limits, Laplace transforms, Taylor series

## Tech Stack
- **Backend:** FastAPI + Python
- **AI:** Google Gemini — `gemini-3.5-flash-lite` for parsing (falls back to `gemini-3.1-flash-lite` on quota limits), `gemini-3.6-flash` for explanations (falls back to `gemini-3.8-flash` on quota limits)
- **Symbolic Engine:** SymPy
- **Database:** Supabase (PostgreSQL)
- **Deployment:** QuikDB Compute

## Running Locally
1. Clone the repo
2. Create a `.env` file using `.env.example` as a template
3. Install dependencies: `pip install -r requirements.txt`
4. Start the server: `uvicorn backend.main:app --reload`
5. Open `http://127.0.0.1:8000`

## Environment Variables
See `.env.example`

## Version Log

| Version | Date | Change |
|---|---|---|
| v1.5 | 2026-09-07 | **Decoupled interpretation testing from the explainer.** Checked real Google AI Studio quota dashboard: `gemini-3.5-flash-lite`/`gemini-3.1-flash-lite` (parser + fallback) have RPM 15, RPD 500 each — ample headroom. `gemini-3.6-flash`/`gemini-3.8-flash` (explainer + fallback) have RPM 5, **RPD only 20 each** — the real bottleneck behind the earlier cascading eval failures. `/solve` now accepts an optional `skip_explanation` flag (default `false`, no change to normal frontend behavior); when `true`, `run_pipeline()` skips the explainer call entirely and the query is not logged to Supabase. `eval_nlp_pipeline.py` (Table 4.9/4.10 interpretation testing) now sends `skip_explanation: true`, so it no longer consumes the explainer's tight daily quota at all — leaving that budget free for the separate explanation-quality run (Tables 4.12/4.13) and end-to-end latency run (Table 4.14), which do need real explanations and must be budgeted/run separately given the 20/day cap. |
| v1.4 | 2026-09-07 | **Added quota-triggered fallback models.** Free-tier Gemini quotas (15 req/min for `gemini-3.5-flash-lite`) caused cascading `/solve` failures under back-to-back testing. `nlp_parser.py` and `explainer.py` now try their primary model first on every call and, only on a 429/quota error, retry that same call once on a fallback model: `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` for parsing, `gemini-3.6-flash` → `gemini-3.8-flash` for explanations. No fallback state persists between calls — the next request always tries the primary model again, so the pipeline switches back automatically once quota resets. The model that actually served a parse is recorded internally as `_model_used`. |
| v1.3 | 2026-09-07 | **Exposed parsed parameters in the `/solve` response.** `QueryResponse` in `backend/main.py` previously returned only `operation` and `expression`, even though `nlp_parser.py` already extracts `variable`, `lower`, `upper`, `point`, and `order` internally. These fields are now included in the API response so downstream evaluation (Table 4.9, parameter-accuracy scoring) can check them directly instead of only checking operation and expression. |
| v1.2 | 2026-08-xx | **Fixed retired-model 404 on deployment.** `gemini-2.5-flash` was retired for new API users after initial deployment, causing silent 404 errors on `/solve`. Updated to current GA models: `gemini-3.5-flash-lite` for parsing (`nlp_parser.py`) and `gemini-3.6-flash` for explanations (`explainer.py`). Updated `GEMINI_API_KEY` in QuikDB deployment settings accordingly. |
| v1.1 | 2026-07-21 | **Migrated AI provider from Anthropic Claude to Google Gemini.** Claude's API credits ran out and, without funding to keep paying for usage, the project moved to Gemini's free tier to keep the app running at zero cost. `nlp_parser.py` (interpretation layer) and `explainer.py` (explanation layer) now use the `google-genai` SDK. Functionally the pipeline architecture `S(I) = G(I, T(E))` is unchanged — only the underlying model provider was swapped. |
| v1.0 | — | Initial build: Claude Haiku (parsing) + Claude Sonnet (explanations), Supabase (PostgreSQL), deployed to QuikDB. |