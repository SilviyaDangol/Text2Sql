# Text-to-SQL Agentic Application

Production-ready natural language to PostgreSQL pipeline using LangGraph agents.

## Architecture

```mermaid
flowchart LR
    U[User Query] --> P[Planner]
    P --> G[SQL Generator]
    G --> V[Validator]
    V -->|valid| E[Executor]
    V -->|invalid| G
    E -->|success| S[Summarizer]
    E -->|error| G
    S --> A[Final Answer]
```

## Quick start

```bash
cd app
cp .env.example .env
# Set OPENAI_API_KEY or GEMINI_API_KEY in .env

docker compose up --build
```

- **Streamlit UI:** http://localhost:8501
- **FastAPI:** http://localhost:8000/docs
- **Application log:** `app/logs/app.log`

## API example

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "List all shipped orders with customer names"}'
```

## Local development (without Docker)

```bash
cd app
python -m venv .venv
source .venv/bin/activate    # note: .venv not venv
pip install -r requirements.txt
export PYTHONPATH="$(cd .. && pwd)"
export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/classicmodels
uvicorn app.main:app --reload
```

## Benchmark evaluation (50 questions)

Run the full `sql_questions_only` CSV through the pipeline and produce grading artifacts:

```bash
# From repo root (Task-4/)
docker compose -f app/docker-compose.yml up -d db
./run_benchmark.sh --limit 3    # smoke test
./run_benchmark.sh                # all 50 questions

# Or explicitly:
export PYTHONPATH="$(pwd)"
python scripts/run_benchmark_evaluation.py --limit 3
```
