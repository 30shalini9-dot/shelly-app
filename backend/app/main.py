from __future__ import annotations

import asyncio
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import database
from .config import CORS_ORIGINS, SEED_DATA
from .schemas import (
    AiVisionNoteCreate,
    AnnotationCreate,
    AnnotationUpdate,
    ChangeQuestionMappingRequest,
    LoginRequest,
    MarkRequest,
    QuestionPaperCreate,
)
from .seed import seed_database


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def create_app(
    seed_data: bool = SEED_DATA, ai_delay_seconds: float = 5
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize_database()
        if seed_data:
            seed_database()
        yield

    app = FastAPI(
        title="Sheldon Evaluation Platform API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def api_root() -> dict[str, str]:
        return {
            "name": "Sheldon Evaluation Platform API",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/login")
    def login(payload: LoginRequest) -> dict[str, str]:
        if payload.username != "evaluator" or payload.password != "password":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Use the demo credentials evaluator / password",
            )
        return {
            "access_token": "local-demo-token",
            "token_type": "bearer",
            "user_id": "eval_001",
            "name": "Evaluator 1",
        }

    @app.post("/auth/logout")
    def logout() -> dict[str, str]:
        return {"message": "Logged out"}

    @app.get("/auth/me")
    def get_current_user() -> dict[str, str]:
        return {
            "user_id": "eval_001",
            "name": "Evaluator 1",
            "role": "evaluator",
        }

    @app.post("/question-papers", status_code=status.HTTP_201_CREATED)
    def add_question_paper(payload: QuestionPaperCreate) -> dict[str, Any]:
        try:
            return database.create_question_paper(payload.model_dump())
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Paper code, question number, or display order already exists",
            ) from exc

    @app.get("/question-papers")
    def get_question_papers() -> list[dict[str, Any]]:
        return database.list_question_papers()

    @app.get("/question-papers/{paper_id_or_code}")
    def get_question_paper(paper_id_or_code: str) -> dict[str, Any]:
        paper = database.get_question_paper(paper_id_or_code)
        if not paper:
            raise HTTPException(status_code=404, detail="Question paper not found")
        return paper

    @app.post("/submissions", status_code=status.HTTP_201_CREATED)
    async def add_submission(
        student_id: Annotated[str, Form(min_length=1)],
        paper_code: Annotated[str, Form(min_length=1)],
        images: Annotated[list[UploadFile], File(min_length=1)],
        student_name: Annotated[str | None, Form()] = None,
        assigned_evaluator_id: Annotated[str, Form()] = "eval_001",
        evaluation_batch: Annotated[str, Form()] = "Default",
    ) -> dict[str, Any]:
        upload_batch = database.new_id("upload")
        upload_dir = database.UPLOAD_DIR / upload_batch
        saved_pages: list[dict[str, Any]] = []
        try:
            upload_dir.mkdir(parents=True, exist_ok=False)
            for index, image in enumerate(images, start=1):
                content_type = image.content_type or "application/octet-stream"
                if content_type not in ALLOWED_IMAGE_TYPES:
                    raise HTTPException(
                        status_code=415,
                        detail=f"{image.filename or 'File'} is not a supported image",
                    )
                data = await image.read(MAX_UPLOAD_BYTES + 1)
                if len(data) > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{image.filename or 'File'} exceeds 15 MB",
                    )
                suffix = Path(image.filename or "").suffix.lower() or ".img"
                stored_file = upload_dir / f"page-{index:03d}{suffix}"
                stored_file.write_bytes(data)
                saved_pages.append(
                    {
                        "original_filename": image.filename or stored_file.name,
                        "stored_path": str(stored_file),
                        "content_type": content_type,
                    }
                )
            return database.create_submission(
                student_id=student_id.strip(),
                student_name=student_name.strip() if student_name else None,
                paper_code=paper_code.strip(),
                assigned_evaluator_id=assigned_evaluator_id.strip(),
                evaluation_batch=evaluation_batch.strip(),
                pages=saved_pages,
            )
        except LookupError as exc:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HTTPException:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise

    @app.get("/evaluations")
    def list_evaluations() -> list[dict[str, Any]]:
        return database.list_evaluations()

    @app.get("/evaluations/{evaluation_id}")
    def get_evaluation(evaluation_id: str) -> dict[str, Any]:
        evaluation = database.get_evaluation(evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return evaluation

    @app.get("/evaluations/{evaluation_id}/pages")
    def get_pages(evaluation_id: str) -> list[dict[str, Any]]:
        pages = database.get_pages(evaluation_id)
        if pages is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return pages

    @app.get("/evaluations/{evaluation_id}/pages/{page_id}/image")
    def get_page_image(evaluation_id: str, page_id: str) -> FileResponse:
        page = database.get_page_file(evaluation_id, page_id)
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        path = Path(page["stored_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Page image is missing on disk")
        return FileResponse(
            path,
            media_type=page["content_type"],
            filename=page["original_filename"],
            content_disposition_type="inline",
        )

    @app.get("/evaluations/{evaluation_id}/questions")
    def get_questions(evaluation_id: str) -> list[dict[str, Any]]:
        questions = database.list_questions(evaluation_id)
        if questions is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return questions

    @app.get("/evaluations/{evaluation_id}/questions/{question_id}")
    def get_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
        question = database.get_question(evaluation_id, question_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return question

    @app.patch("/evaluations/{evaluation_id}/questions/{question_id}/focus")
    def focus_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
        try:
            return database.focus_question(evaluation_id, question_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/evaluations/{evaluation_id}/questions/{question_id}/steps")
    def get_question_steps(evaluation_id: str, question_id: str) -> list[dict[str, Any]]:
        question = database.get_question(evaluation_id, question_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return question["steps"]

    @app.post("/evaluations/{evaluation_id}/steps/{step_id}/marks")
    @app.patch("/evaluations/{evaluation_id}/steps/{step_id}/marks")
    def save_marks(
        evaluation_id: str, step_id: str, payload: MarkRequest
    ) -> dict[str, Any]:
        try:
            return database.save_step_mark(
                evaluation_id, step_id, payload.awarded_marks
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/evaluations/{evaluation_id}/questions/{question_id}/full-marks")
    def full_marks(evaluation_id: str, question_id: str) -> dict[str, Any]:
        try:
            return database.assign_full_marks(evaluation_id, question_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/evaluations/{evaluation_id}/questions/{question_id}/marks")
    def reset_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
        try:
            return database.reset_question(evaluation_id, question_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/evaluations/{evaluation_id}/annotations")
    def get_annotations(evaluation_id: str) -> list[dict[str, Any]]:
        annotations = database.list_annotations(evaluation_id)
        if annotations is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return annotations

    @app.post(
        "/evaluations/{evaluation_id}/annotations",
        status_code=status.HTTP_201_CREATED,
    )
    def add_annotation(
        evaluation_id: str, payload: AnnotationCreate
    ) -> dict[str, Any]:
        try:
            return database.create_annotation(evaluation_id, payload.model_dump())
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/evaluations/{evaluation_id}/annotations/{annotation_id}")
    def resize_annotation(
        evaluation_id: str,
        annotation_id: str,
        payload: AnnotationUpdate,
    ) -> dict[str, Any]:
        try:
            return database.update_annotation(
                evaluation_id,
                annotation_id,
                payload.model_dump(),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/evaluations/{evaluation_id}/ai-vision-notes")
    def get_ai_vision_notes(evaluation_id: str) -> list[dict[str, Any]]:
        notes = database.list_ai_vision_notes(evaluation_id)
        if notes is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return notes

    @app.post(
        "/evaluations/{evaluation_id}/ai-vision-notes",
        status_code=status.HTTP_201_CREATED,
    )
    def save_ai_vision_note(
        evaluation_id: str, payload: AiVisionNoteCreate
    ) -> dict[str, Any]:
        try:
            return database.create_ai_vision_note(
                evaluation_id, payload.model_dump()
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete(
        "/evaluations/{evaluation_id}/ai-vision-notes/{note_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_ai_vision_note(evaluation_id: str, note_id: str) -> None:
        try:
            database.delete_ai_vision_note(evaluation_id, note_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/evaluations/{evaluation_id}/ai-vision",
        status_code=status.HTTP_201_CREATED,
    )
    async def analyze_answer_selection(
        evaluation_id: str,
        question_id: Annotated[str, Form(min_length=1)],
        page_id: Annotated[str, Form(min_length=1)],
        question_text: Annotated[str, Form(min_length=1)],
        x: Annotated[float, Form(ge=0, le=1)],
        y: Annotated[float, Form(ge=0, le=1)],
        width: Annotated[float, Form(gt=0, le=1)],
        height: Annotated[float, Form(gt=0, le=1)],
        crop: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        content_type = crop.content_type or "application/octet-stream"
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Crop must be an image")
        crop_bytes = await crop.read(MAX_UPLOAD_BYTES + 1)
        if not crop_bytes:
            raise HTTPException(status_code=422, detail="Crop image is empty")
        if len(crop_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Crop exceeds 15 MB")
        await asyncio.sleep(ai_delay_seconds)
        try:
            return database.preview_ai_vision_note(
                evaluation_id,
                question_id=question_id,
                page_id=page_id,
                question_text=question_text,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/evaluations/{evaluation_id}/questions/{question_id}/next")
    def next_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
        question = database.adjacent_question(evaluation_id, question_id, 1)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return question

    @app.post("/evaluations/{evaluation_id}/questions/{question_id}/previous")
    def previous_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
        question = database.adjacent_question(evaluation_id, question_id, -1)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return question

    @app.post(
        "/evaluations/{evaluation_id}/questions/{question_id}/change-mapping"
    )
    def change_mapping(
        evaluation_id: str,
        question_id: str,
        payload: ChangeQuestionMappingRequest,
    ) -> dict[str, Any]:
        try:
            return database.change_mapping(
                evaluation_id,
                question_id,
                payload.to_question_id,
                payload.page_id,
                payload.bbox,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/evaluations/{evaluation_id}/progress")
    def get_progress(evaluation_id: str) -> dict[str, Any]:
        progress = database.get_progress(evaluation_id)
        if not progress:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return progress

    @app.get("/evaluations/{evaluation_id}/marks-summary")
    def get_marks_summary(evaluation_id: str) -> dict[str, Any]:
        summary = database.get_marks_summary(evaluation_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return summary

    @app.post("/evaluations/{evaluation_id}/submit")
    def submit_evaluation(evaluation_id: str) -> dict[str, Any]:
        try:
            return database.submit_evaluation(evaluation_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
