# Sheldon FastAPI backend

Run from this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed --reset
uvicorn app.main:app --reload
```

Interactive API docs are available at `http://localhost:8000/docs`.

The database and uploaded images are local:

```text
data/sheldon.db
data/uploads/
```

See the repository root `README.md` for complete question-paper JSON, image
upload examples, environment settings, reset commands, and endpoint details.
