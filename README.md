# Sheldon Evaluation Platform

Sheldon is a local answer-sheet evaluation application built from the supplied
`PRD.md`, `BACKEND.md`, and `DB.md`.

- `frontend/`: React + TypeScript + Vite
- `backend/`: FastAPI + embedded SQLite
- Answer sheet images: local files under `backend/data/uploads/`
- API documentation: `http://localhost:8000/docs`

SQLite is an embedded Python database. It requires no database server, keeps
data between restarts, and can be deleted and recreated with one command.

## Quick start

### 1. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed --reset
uvicorn app.main:app --reload
```

The backend runs at `http://localhost:8000`. The first normal startup also
creates the database and sample data when the database is empty.

### 2. Start the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and sign in with:

```text
Username: evaluator
Password: password
```

Use **Add data** in the application to create a question paper from JSON and
upload a student's page images.

## Local data

The default local paths are:

```text
backend/data/sheldon.db
backend/data/uploads/
```

They are intentionally excluded from Git. Configure different paths with:

```bash
export SHELDON_DATABASE_PATH=data/my-school.db
export SHELDON_UPLOAD_DIR=data/my-school-uploads
```

Reset the database and reload the sample paper/submission:

```bash
cd backend
python -m app.seed --reset
```

Load sample data only when the database is empty:

```bash
python -m app.seed
```

Disable automatic sample loading:

```bash
export SHELDON_SEED_DATA=false
```

## Add a question paper

Question papers contain their questions, marking steps, and reference
solutions. The sum of step marks must equal the question's `max_marks`.

```bash
curl -X POST http://localhost:8000/question-papers \
  -H 'Content-Type: application/json' \
  -d '{
    "paper_code": "MATH-10-A",
    "subject_code": "MATH",
    "subject_name": "Mathematics",
    "class_code": "10",
    "version": 1,
    "status": "active",
    "questions": [
      {
        "question_no": "Q1",
        "question_text": "Solve 2x + 4 = 10.",
        "max_marks": 2,
        "question_type": "Short Answer",
        "display_order": 1,
        "reference_solution": "2x = 6, therefore x = 3.",
        "steps": [
          {
            "step_no": 1,
            "title": "Rearrangement",
            "description": "Subtracts 4 from both sides.",
            "max_marks": 1
          },
          {
            "step_no": 2,
            "title": "Final value",
            "description": "Divides by 2 and obtains x = 3.",
            "max_marks": 1
          }
        ]
      }
    ]
  }'
```

Useful paper endpoints:

```text
POST /question-papers
GET  /question-papers
GET  /question-papers/{paper_id_or_code}
```

Paper codes are unique and case-insensitive.

## Add a student submission and page images

Create the paper first, then upload one or more answer-sheet images. Images are
stored in the order supplied. Supported formats are PNG, JPEG, WebP, GIF, and
SVG, with a maximum size of 15 MB per image.

```bash
curl -X POST http://localhost:8000/submissions \
  -F 'student_id=STU002' \
  -F 'student_name=Asha Kumar' \
  -F 'paper_code=MATH-10-A' \
  -F 'assigned_evaluator_id=eval_001' \
  -F 'evaluation_batch=June 2026' \
  -F 'images=@/absolute/path/page-1.png' \
  -F 'images=@/absolute/path/page-2.png'
```

The response contains the new `evaluation_id`. Questions are initially mapped
to uploaded pages in display order; mappings can later be changed through:

```text
POST /evaluations/{evaluation_id}/questions/{question_id}/change-mapping
```

## Evaluation API

Core endpoints:

```text
POST  /auth/login
GET   /evaluations
GET   /evaluations/{evaluation_id}
GET   /evaluations/{evaluation_id}/pages
GET   /evaluations/{evaluation_id}/pages/{page_id}/image
GET   /evaluations/{evaluation_id}/questions
GET   /evaluations/{evaluation_id}/questions/{question_id}
PATCH /evaluations/{evaluation_id}/questions/{question_id}/focus
POST  /evaluations/{evaluation_id}/steps/{step_id}/marks
PATCH /evaluations/{evaluation_id}/steps/{step_id}/marks
POST  /evaluations/{evaluation_id}/questions/{question_id}/full-marks
DELETE /evaluations/{evaluation_id}/questions/{question_id}/marks
GET   /evaluations/{evaluation_id}/annotations
POST  /evaluations/{evaluation_id}/annotations
PATCH /evaluations/{evaluation_id}/annotations/{annotation_id}
GET   /evaluations/{evaluation_id}/ai-vision-notes
POST  /evaluations/{evaluation_id}/ai-vision-notes
DELETE /evaluations/{evaluation_id}/ai-vision-notes/{note_id}
POST  /evaluations/{evaluation_id}/ai-vision
GET   /evaluations/{evaluation_id}/progress
GET   /evaluations/{evaluation_id}/marks-summary
POST  /evaluations/{evaluation_id}/submit
```

Assign a step mark:

```bash
curl -X POST \
  http://localhost:8000/evaluations/EV_ID/steps/STEP_ID/marks \
  -H 'Content-Type: application/json' \
  -d '{"awarded_marks": 0.5}'
```

The backend rejects negative marks and marks above the step maximum.
An evaluation can only be submitted after every step has a mark.
Resetting a question removes its step marks and answer-sheet mark labels.

## AI Vision reference notes

In the evaluation workspace, right-click an answer page and choose
**AI Vision selection**, then drag a rectangle around the answer area. The
frontend sends the cropped image, current question text, page, and rectangle
coordinates as multipart form data:

```bash
curl -X POST http://localhost:8000/evaluations/EV_ID/ai-vision \
  -F 'question_id=QUESTION_ID' \
  -F 'page_id=PAGE_ID' \
  -F 'question_text=Define photosynthesis.' \
  -F 'x=0.2' \
  -F 'y=0.3' \
  -F 'width=0.4' \
  -F 'height=0.15' \
  -F 'crop=@/absolute/path/answer-selection.png'
```

The current endpoint is a local dummy implementation. It waits five seconds
and returns transient reference text without calling an external AI service.
The selection rectangle is removed when the response arrives. Use the response
card's **Save** action to store the note in SQLite and minimize it to a circular
marker on the answer page, or **Delete** to discard it.

Save the returned analysis and coordinates:

```text
POST /evaluations/{evaluation_id}/ai-vision-notes
```

Saved notes can be reloaded or removed with:

```text
GET /evaluations/{evaluation_id}/ai-vision-notes
DELETE /evaluations/{evaluation_id}/ai-vision-notes/{note_id}
```

## Tests and builds

```bash
cd backend
source .venv/bin/activate
python -m unittest discover -s tests -v
```

```bash
cd frontend
npm run build
```

## Database tables

The backend creates these normalized SQLite tables automatically:

```text
question_papers
questions
question_steps
student_submissions
submission_pages
submission_question_mappings
evaluations
evaluation_step_marks
answer_annotations
ai_vision_notes
```

Do not edit the SQLite file by hand for normal data entry. Use the **Add data**
screen, API, or seed module so validation and relationships remain correct.
