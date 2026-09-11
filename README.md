# Studify 🎓

An AI-powered engineering mathematics tutor for undergraduate students.
Ask any calculus, mechanics, or control systems question in plain English
and get a symbolic result plus a step-by-step explanation.

## Live Demo
[https://studify.quikdb.net](https://studify.quikdb.net)

## Features
- Natural language math queries
- **Snap or upload a photo of a math problem** — Gemini vision transcribes it into a plain-text query, shown back to you for confirmation/editing before solving
- Symbolic computation via SymPy
- Step-by-step AI explanations powered by Google Gemini
- Query history saved to Supabase
- Supports: derivatives, integrals, limits, Laplace transforms, Taylor series

## Tech Stack
- **Backend:** FastAPI + Python
- **AI:** Google Gemini — `gemini-3.5-flash-lite` for parsing and vision transcription (falls back to `gemini-3.1-flash-lite` on quota/availability issues), `gemini-3.8-flash` for explanations (falls back to `gemini-3.7-flash` on quota/availability issues)
- **Evaluation LLM Judge:** `nvidia/nemotron-3.5-lightning:free` via OpenRouter, used by `eval_pipeline_results.py` to score explanation quality (Tables 4.12–4.14)
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
| v1.9 | 2026-09-11 | **Broadened model fallback to cover transient server overload, not just quota.** The retry logic in `nlp_parser.py`, `vision_parser.py`, and `explainer.py` previously only fell back to the secondary model on a 429/quota error (`_is_quota_error`). A `503 UNAVAILABLE` response from Gemini (transient demand-side overload, unrelated to our own quota) was falling through the same `except` block uncaught by that check, so `explainer.py` was returning the raw error string as if it were an explanation. Added `_is_retryable_error()`, which covers `_is_quota_error()`'s cases plus `503`/`UNAVAILABLE`/"overloaded", and switched all three modules' fallback trigger to use it. Same no-persistent-state fallback behavior as before — next call still tries the primary model first. |
| v1.8 | 2026-09-11 | **Added computer vision input.** New entry point lets a photo of a handwritten or printed math problem be solved the same way a typed query is. `backend/vision_parser.py` (new) reuses the parser's fallback model pair (`gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`, *not* the tight-quota explainer model) to transcribe an uploaded image into a plain-text query, which is then handed to the existing `run_pipeline()` unchanged — vision is purely an additional input modality feeding the same `S(I) = G(I, T(E))` pipeline, not a separate pipeline. New `POST /solve-image` endpoint in `main.py` accepts a multipart image upload (JPEG/PNG/WEBP, 8MB cap), returns the extracted text alongside the normal solve response so the frontend can show it back to the user for confirmation/editing before it's treated as ground truth. Frontend (`index.html`/`app.js`/`style.css`) adds a camera button next to the text input that opens the native camera-or-gallery picker on mobile (no `capture` attribute, so both options are offered) and a confirm modal with an editable extracted-text field, Solve, Retake, and Cancel. Added `python-multipart` to `requirements.txt` (required by FastAPI for multipart form/file uploads, previously unneeded since no endpoint accepted files). |
| v1.7 | 2026-09-09 | **Swapped LLM judge model for quality-metric evaluation.** Multiple free-tier Qwen model slugs used by `eval_pipeline_results.py` (Tables 4.12–4.14 explanation-quality scoring) became unavailable on OpenRouter mid-project. Switched the judge model to `nvidia/nemotron-3.5-lightning:free`, also via OpenRouter. This only affects the offline evaluation scripts, not the live `/solve` pipeline — Gemini models for parsing and explanation are unchanged. |
| v1.6 | 2026-09-07 | **Swapped explainer models; silenced a benign SDK warning.** Explainer primary/fallback pair changed from `gemini-3.6-flash`/`gemini-3.8-flash` to `gemini-3.8-flash`/`gemini-3.7-flash`. Both replacement models carry the same RPM 5 / RPD 20 quota as the pair they replace (confirmed against the Google AI Studio dashboard), so the tight daily explainer budget noted in v1.5 is unchanged — this was a model-quality choice, not a quota fix. Separately, QuikDB logs showed a recurring SDK warning ("Direct use of automatic function calling (AFC) in Models.generate_content is not recommended..."). This is a known google-genai SDK quirk that fires even when no tools/function-calling are configured (tracked upstream as `googleapis/python-genai#2902`) — Studify never uses function calling, so the warning was noise, not a bug. `automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)` was added to both `nlp_parser.py`'s and `explainer.py`'s `GenerateContentConfig` to silence it explicitly, which also future-proofs against an upcoming breaking SDK change that removes direct-call AFC entirely. |
| v1.5 | 2026-09-07 | **Decoupled interpretation testing from the explainer.** Checked real Google AI Studio quota dashboard: `gemini-3.5-flash-lite`/`gemini-3.1-flash-lite` (parser + fallback) have RPM 15, RPD 500 each — ample headroom. `gemini-3.6-flash`/`gemini-3.8-flash` (explainer + fallback, since superseded by v1.6) have RPM 5, **RPD only 20 each** — the real bottleneck behind the earlier cascading eval failures. `/solve` now accepts an optional `skip_explanation` flag (default `false`, no change to normal frontend behavior); when `true`, `run_pipeline()` skips the explainer call entirely and the query is not logged to Supabase. `eval_nlp_pipeline.py` (Table 4.9/4.10 interpretation testing) now sends `skip_explanation: true`, so it no longer consumes the explainer's tight daily quota at all — leaving that budget free for the separate explanation-quality run (Tables 4.12/4.13) and end-to-end latency run (Table 4.14), which do need real explanations and must be budgeted/run separately given the 20/day cap. |
| v1.4 | 2026-09-07 | **Added quota-triggered fallback models.** Free-tier Gemini quotas (15 req/min for `gemini-3.5-flash-lite`) caused cascading `/solve` failures under back-to-back testing. `nlp_parser.py` and `explainer.py` now try their primary model first on every call and, only on a 429/quota error, retry that same call once on a fallback model: `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` for parsing, `gemini-3.6-flash` → `gemini-3.8-flash` for explanations. No fallback state persists between calls — the next request always tries the primary model again, so the pipeline switches back automatically once quota resets. The model that actually served a parse is recorded internally as `_model_used`. |
| v1.3 | 2026-09-07 | **Exposed parsed parameters in the `/solve` response.** `QueryResponse` in `backend/main.py` previously returned only `operation` and `expression`, even though `nlp_parser.py` already extracts `variable`, `lower`, `upper`, `point`, and `order` internally. These fields are now included in the API response so downstream evaluation (Table 4.9, parameter-accuracy scoring) can check them directly instead of only checking operation and expression. |
| v1.2 | 2026-08-xx | **Fixed retired-model 404 on deployment.** `gemini-2.5-flash` was retired for new API users after initial deployment, causing silent 404 errors on `/solve`. Updated to current GA models: `gemini-3.5-flash-lite` for parsing (`nlp_parser.py`) and `gemini-3.6-flash` for explanations (`explainer.py`). Updated `GEMINI_API_KEY` in QuikDB deployment settings accordingly. |
| v1.1 | 2026-07-21 | **Migrated AI provider from Anthropic Claude to Google Gemini.** Claude's API credits ran out and, without funding to keep paying for usage, the project moved to Gemini's free tier to keep the app running at zero cost. `nlp_parser.py` (interpretation layer) and `explainer.py` (explanation layer) now use the `google-genai` SDK. Functionally the pipeline architecture `S(I) = G(I, T(E))` is unchanged — only the underlying model provider was swapped. |
| v1.0 | — | Initial build: Claude Haiku (parsing) + Claude Sonnet (explanations), Supabase (PostgreSQL), deployed to QuikDB. |