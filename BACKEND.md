Below is a minimal FastAPI API set for Sheldon MVP.

AUTH
POST   /auth/login
POST   /auth/logout
GET    /auth/me
DASHBOARD
GET    /evaluations
GET    /evaluations/{evaluation_id}
ANSWER SHEET / PAGES
GET    /evaluations/{evaluation_id}/pages
GET    /evaluations/{evaluation_id}/pages/{page_id}/image
QUESTIONS
GET    /evaluations/{evaluation_id}/questions
GET    /evaluations/{evaluation_id}/questions/{question_id}
PATCH  /evaluations/{evaluation_id}/questions/{question_id}/focus
STEP MARKING
GET    /evaluations/{evaluation_id}/questions/{question_id}/steps
POST   /evaluations/{evaluation_id}/steps/{step_id}/marks
PATCH  /evaluations/{evaluation_id}/steps/{step_id}/marks
RIGHT CLICK ACTIONS
POST   /evaluations/{evaluation_id}/questions/{question_id}/full-marks
POST   /evaluations/{evaluation_id}/questions/{question_id}/next
POST   /evaluations/{evaluation_id}/questions/{question_id}/previous
QUESTION MAPPING
POST   /evaluations/{evaluation_id}/questions/{question_id}/change-mapping
PROGRESS / TOTALS
GET    /evaluations/{evaluation_id}/progress
GET    /evaluations/{evaluation_id}/marks-summary
COMPLETION
POST   /evaluations/{evaluation_id}/submit

Minimal Data Models

class LoginRequest(BaseModel):
    username: str
    password: str
class MarkRequest(BaseModel):
    awarded_marks: float
class ChangeQuestionMappingRequest(BaseModel):
    from_question_id: str
    to_question_id: str
    page_id: str | None = None
    bbox: dict | None = None
class EvaluationStatus(str, Enum):
    not_started = "Not Started"
    in_progress = "In Progress"
    completed = "Completed"
class StepStatus(str, Enum):
    pending = "Pending"
    completed = "Completed"

Most Important MVP APIs

1. POST /auth/login
2. GET /evaluations
3. GET /evaluations/{evaluation_id}
4. GET /evaluations/{evaluation_id}/pages
5. GET /evaluations/{evaluation_id}/questions
6. POST /evaluations/{evaluation_id}/steps/{step_id}/marks
7. POST /evaluations/{evaluation_id}/questions/{question_id}/full-marks
8. POST /evaluations/{evaluation_id}/questions/{question_id}/change-mapping
9. GET /evaluations/{evaluation_id}/progress
10. POST /evaluations/{evaluation_id}/submit

Minimal FastAPI Skeleton

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from enum import Enum
app = FastAPI(title="Sheldon Evaluation Platform API")
class LoginRequest(BaseModel):
    username: str
    password: str
class MarkRequest(BaseModel):
    awarded_marks: float
class ChangeQuestionMappingRequest(BaseModel):
    from_question_id: str
    to_question_id: str
    page_id: str | None = None
    bbox: dict | None = None
@app.post("/auth/login")
def login(payload: LoginRequest):
    return {"access_token": "mock-token", "token_type": "bearer"}
@app.get("/auth/me")
def get_current_user():
    return {
        "user_id": "eval_001",
        "name": "Evaluator 1",
        "role": "evaluator"
    }
@app.get("/evaluations")
def list_evaluations():
    return [
        {
            "evaluation_id": "ev_001",
            "student_id": "STU001",
            "subject": "Science",
            "question_paper_code": "SCI-10-A",
            "status": "In Progress",
            "marks_awarded": 32.5,
            "max_marks": 50
        }
    ]
@app.get("/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str):
    return {
        "evaluation_id": evaluation_id,
        "student_id": "STU001",
        "metadata": {
            "subject_code": "SCI",
            "class_code": "10",
            "question_paper_code": "SCI-10-A",
            "total_questions": 20,
            "maximum_marks": 50
        }
    }
@app.get("/evaluations/{evaluation_id}/pages")
def get_pages(evaluation_id: str):
    return [
        {
            "page_id": "page_001",
            "page_number": 1,
            "image_url": f"/evaluations/{evaluation_id}/pages/page_001/image"
        }
    ]
@app.get("/evaluations/{evaluation_id}/questions")
def get_questions(evaluation_id: str):
    return [
        {
            "question_id": "q4",
            "question_no": "Q4",
            "max_marks": 5,
            "awarded_marks": 3.5,
            "status": "In Progress",
            "page_id": "page_003",
            "bbox": {"x": 100, "y": 420, "w": 900, "h": 500}
        }
    ]
@app.get("/evaluations/{evaluation_id}/questions/{question_id}")
def get_question(evaluation_id: str, question_id: str):
    return {
        "question_id": question_id,
        "question_no": "Q4",
        "question_text": "Explain the process of photosynthesis.",
        "max_marks": 5,
        "question_type": "Long Answer",
        "steps": [
            {
                "step_id": "step_001",
                "title": "Definition",
                "max_marks": 1,
                "awarded_marks": 1,
                "status": "Completed"
            },
            {
                "step_id": "step_002",
                "title": "Diagram",
                "max_marks": 2,
                "awarded_marks": 2,
                "status": "Completed"
            },
            {
                "step_id": "step_003",
                "title": "Explanation",
                "max_marks": 2,
                "awarded_marks": 0.5,
                "status": "In Progress"
            }
        ],
        "reference_solution": "Photosynthesis is the process by which green plants prepare food using sunlight, carbon dioxide and water."
    }
@app.post("/evaluations/{evaluation_id}/steps/{step_id}/marks")
def assign_step_marks(evaluation_id: str, step_id: str, payload: MarkRequest):
    if payload.awarded_marks < 0:
        raise HTTPException(status_code=400, detail="Marks cannot be negative")
    return {
        "evaluation_id": evaluation_id,
        "step_id": step_id,
        "awarded_marks": payload.awarded_marks,
        "message": "Marks saved successfully"
    }
@app.post("/evaluations/{evaluation_id}/questions/{question_id}/full-marks")
def assign_full_marks(evaluation_id: str, question_id: str):
    return {
        "evaluation_id": evaluation_id,
        "question_id": question_id,
        "status": "Completed",
        "message": "Full marks assigned"
    }
@app.post("/evaluations/{evaluation_id}/questions/{question_id}/change-mapping")
def change_question_mapping(
    evaluation_id: str,
    question_id: str,
    payload: ChangeQuestionMappingRequest
):
    return {
        "evaluation_id": evaluation_id,
        "from_question_id": payload.from_question_id,
        "to_question_id": payload.to_question_id,
        "message": "Question mapping updated successfully"
    }
@app.get("/evaluations/{evaluation_id}/progress")
def get_progress(evaluation_id: str):
    return {
        "questions_viewed": 8,
        "total_questions": 20,
        "questions_evaluated": 6,
        "total_marks": 32.5,
        "maximum_marks": 50,
        "completion_percentage": 65
    }
@app.get("/evaluations/{evaluation_id}/marks-summary")
def get_marks_summary(evaluation_id: str):
    return {
        "evaluation_id": evaluation_id,
        "question_marks": [
            {"question_no": "Q1", "awarded": 2, "max": 2},
            {"question_no": "Q2", "awarded": 4, "max": 5},
            {"question_no": "Q3", "awarded": 3.5, "max": 5}
        ],
        "total_awarded": 32.5,
        "maximum_marks": 50
    }
@app.post("/evaluations/{evaluation_id}/submit")
def submit_evaluation(evaluation_id: str):
    return {
        "evaluation_id": evaluation_id,
        "status": "Completed",
        "message": "Evaluation submitted successfully"
    }

Area	API Count
Auth	3
Dashboard	2
Pages	2
Questions	3
Marking	3
Mapping	1
Progress	2
Completion	1