# Studify 🎓

An AI-powered engineering mathematics tutor for undergraduate students.
Ask any calculus, mechanics, or control systems question in plain English
and get a symbolic result plus a step-by-step explanation.

## Live Demo
[https://studify.quikdb.net] ← fill this in after deployment

## Features
- Natural language math queries
- Symbolic computation via SymPy
- Step-by-step AI explanations powered by Claude
- Query history saved to Supabase
- Supports: derivatives, integrals, limits, Laplace transforms, Taylor series

## Tech Stack
- **Backend:** FastAPI + Python
- **AI:** Anthropic Claude (Haiku for parsing, Sonnet for explanations)
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
