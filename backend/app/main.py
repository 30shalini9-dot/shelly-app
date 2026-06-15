from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import database
from .ai_vision import (
    MODEL,
    SYSTEM_PROMPT,
    build_evaluation_prompt,
    evaluate_answer,
    normalize_step_marks,
)
from .config import AI_VISION_RUN_DIR, CORS_ORIGINS, SEED_DATA
from .schemas import (
    AiVisionAcceptRequest,
    AiVisionRejectRequest,
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


def _load_ai_vision_run(
    root: Path,
    run_id: str,
    evaluation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = root / run_id
    try:
        metadata = json.loads((run_dir / "metadata.json").read_text("utf-8"))
        result = json.loads((run_dir / "result.json").read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise LookupError("AI Vision run was not found or is incomplete") from exc
    if metadata.get("evaluation_id") != evaluation_id:
        raise LookupError("AI Vision run does not belong to this evaluation")
    return metadata, result


def _write_run_decision(
    root: Path,
    run_id: str,
    evaluation_id: str,
    decision: str,
) -> None:
    metadata, _ = _load_ai_vision_run(root, run_id, evaluation_id)
    metadata["decision"] = decision
    (root / run_id / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _record_run_error(
    run_dir: Path,
    metadata: dict[str, Any],
    error: Exception,
) -> None:
    if not run_dir.exists():
        return
    metadata["status"] = "error"
    metadata["error"] = str(error)
    try:
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "error.txt").write_text(str(error), encoding="utf-8")
    except OSError:
        pass


def create_app(
    seed_data: bool = SEED_DATA,
    ai_delay_seconds: float = 0,
    ai_evaluator: Callable[[str, str], dict[str, Any]] | None = None,
    ai_vision_run_dir: Path = AI_VISION_RUN_DIR,
) -> FastAPI:
    evaluate_image = ai_evaluator or (
        lambda prompt, image_path: evaluate_answer(
            question=prompt,
            image_path=image_path,
        )
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize_database()
        ai_vision_run_dir.mkdir(parents=True, exist_ok=True)
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

    @app.delete("/evaluations/{evaluation_id}/marks")
    def reset_evaluation_marks(evaluation_id: str) -> dict[str, Any]:
        try:
            return database.reset_evaluation_marks(evaluation_id)
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

    @app.post(
        "/evaluations/{evaluation_id}/ai-vision",
        status_code=status.HTTP_201_CREATED,
    )
    async def analyze_answer_selection(
        evaluation_id: str,
        question_id: Annotated[str, Form(min_length=1)],
        page_id: Annotated[str, Form(min_length=1)],
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
        question = database.get_question(evaluation_id, question_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        pages = database.get_pages(evaluation_id)
        if pages is None or not any(page["page_id"] == page_id for page in pages):
            raise HTTPException(status_code=404, detail="Answer-sheet page not found")

        prompt = build_evaluation_prompt(
            question_text=question["question_text"],
            reference_solution=question["reference_solution"],
            steps=question["steps"],
        )
        suffix = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
        }.get(content_type, ".img")
        run_id = database.new_id("run")
        run_dir = ai_vision_run_dir / run_id
        image_path = run_dir / f"answer-selection{suffix}"
        metadata = {
            "run_id": run_id,
            "evaluation_id": evaluation_id,
            "question_id": question_id,
            "question_no": question["question_no"],
            "page_id": page_id,
            "content_type": content_type,
            "selection": {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
            "status": "running",
        }
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            image_path.write_bytes(crop_bytes)
            (run_dir / "context.txt").write_text(
                "\n\n".join(
                    (
                        f"Run ID:\n{run_id}",
                        f"Model:\n{MODEL}",
                        f"Image sent to Ollama:\n{image_path.resolve()}",
                        f"System Prompt:\n{SYSTEM_PROMPT}",
                        f"User Prompt:\n{prompt}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if ai_delay_seconds:
                await asyncio.sleep(ai_delay_seconds)
            result = await asyncio.to_thread(
                evaluate_image,
                prompt,
                str(image_path),
            )
            marks = normalize_step_marks(
                result,
                [step["max_marks"] for step in question["steps"]],
            )
            reasoning = str(result.get("reasoning", "")).strip()
            (run_dir / "model-response.json").write_text(
                json.dumps(
                    result.get("raw_response", result),
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )
            normalized_result = {
                "run_id": run_id,
                "marks": marks,
                "reasoning": reasoning,
            }
            (run_dir / "result.json").write_text(
                json.dumps(normalized_result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            metadata["status"] = "ready"
            (run_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (ConnectionError, OSError, RuntimeError) as exc:
            _record_run_error(run_dir, metadata, exc)
            raise HTTPException(
                status_code=503,
                detail=f"Local AI Vision service is unavailable: {exc}",
            ) from exc
        except Exception as exc:
            _record_run_error(run_dir, metadata, exc)
            raise HTTPException(
                status_code=502,
                detail=f"AI Vision returned an invalid response: {exc}",
            ) from exc

        return {
            "run_id": run_id,
            "question_id": question_id,
            "page_id": page_id,
            "question_no": question["question_no"],
            "marks": marks,
            "steps": [
                {
                    "step_id": step["step_id"],
                    "step_no": step["step_no"],
                    "title": step["title"],
                    "max_marks": step["max_marks"],
                    "awarded_marks": mark,
                }
                for step, mark in zip(question["steps"], marks)
            ],
            "awarded_marks": sum(marks),
            "max_marks": question["max_marks"],
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            # Reserved for a future rationale UI. The backend and run artifacts
            # retain this value, but the current frontend intentionally hides it.
            "reasoning": reasoning,
        }

    @app.post("/evaluations/{evaluation_id}/ai-vision/accept")
    def accept_ai_vision_result(
        evaluation_id: str,
        payload: AiVisionAcceptRequest,
    ) -> dict[str, Any]:
        question = database.get_question(evaluation_id, payload.question_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        try:
            metadata, run_result = _load_ai_vision_run(
                ai_vision_run_dir,
                payload.run_id,
                evaluation_id,
            )
            if (
                metadata.get("question_id") != payload.question_id
                or metadata.get("page_id") != payload.page_id
            ):
                raise ValueError("AI Vision run does not match this question")
            marks = normalize_step_marks(
                run_result.get("marks", payload.marks),
                [step["max_marks"] for step in question["steps"]],
            )
            selection = metadata.get("selection", {})
            result = database.accept_ai_vision_marks(
                evaluation_id,
                question_id=payload.question_id,
                page_id=payload.page_id,
                marks=marks,
                x=float(selection.get("x", payload.x)),
                y=float(selection.get("y", payload.y)),
                width=float(selection.get("width", payload.width)),
                height=float(selection.get("height", payload.height)),
                reasoning=str(run_result.get("reasoning", "")).strip(),
            )
            _write_run_decision(
                ai_vision_run_dir,
                payload.run_id,
                evaluation_id,
                "accepted",
            )
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/evaluations/{evaluation_id}/ai-vision/reject")
    def reject_ai_vision_result(
        evaluation_id: str,
        payload: AiVisionRejectRequest,
    ) -> dict[str, str]:
        if not database.get_evaluation(evaluation_id):
            raise HTTPException(status_code=404, detail="Evaluation not found")
        try:
            _write_run_decision(
                ai_vision_run_dir,
                payload.run_id,
                evaluation_id,
                "rejected",
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "rejected"}

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
