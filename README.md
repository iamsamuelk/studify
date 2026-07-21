# Studify 🎓

An AI-powered engineering mathematics tutor for undergraduate students.
Ask any calculus, mechanics, or control systems question in plain English
and get a symbolic result plus a step-by-step explanation.

## Live Demo
[your-app.quikdb.net](https://your-app.quikdb.net) ← fill this in after deployment

## Features
- Natural language math queries
- Symbolic computation via SymPy
- Step-by-step AI explanations powered by Google Gemini
- Query history saved to Supabase
- Supports: derivatives, integrals, limits, Laplace transforms, Taylor series

## Tech Stack
- **Backend:** FastAPI + Python
- **AI:** Google Gemini (Gemini 2.5 Flash for parsing, Gemini 2.5 Pro for explanations)
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
| v1.1 | 2026-07-21 | **Migrated AI provider from Anthropic Claude to Google Gemini.** Claude's API credits ran out and, without funding to keep paying for usage, the project moved to Gemini's free tier to keep the app running at zero cost. `nlp_parser.py` (interpretation layer) now uses `gemini-2.5-flash`, and `explainer.py` (explanation layer) now uses `gemini-2.5-pro`, both via the `google-genai` SDK. Functionally the pipeline architecture `S(I) = G(I, T(E))` is unchanged — only the underlying model provider was swapped. |
| v1.0 | — | Initial build: Claude Haiku (parsing) + Claude Sonnet (explanations), Supabase (PostgreSQL), deployed to QuikDB. |