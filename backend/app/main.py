from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import database
from .agent_workflow import (
    fetch_cornerstone_status,
    fetch_agent_image,
    submit_cornerstone_job,
    valid_cornerstone_signature,
)
from .ai_vision import (
    MODEL,
    SYSTEM_PROMPT,
    build_evaluation_prompt,
    evaluate_answer,
    normalize_step_marks,
)
from .config import (
    AGENT_DUMMY_FULL_MARKS,
    AGENT_JOB_RUN_DIR,
    AI_VISION_RUN_DIR,
    CORNERSTONE_API_URL,
    CORNERSTONE_WEBHOOK_SECRET,
    CORS_ORIGINS,
    PUBLIC_API_URL,
    SEED_DATA,
)
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


def _cornerstone_question_group_key(
    question: dict[str, Any],
    fallback_index: int,
) -> str:
    question_no = question.get("question_no")
    if question_no is None:
        return f"index:{fallback_index}"
    normalized = str(question_no).strip()
    if not normalized:
        return f"index:{fallback_index}"
    return f"question:{normalized}"


def _group_cornerstone_question_segments(
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for index, question in enumerate(questions):
        key = _cornerstone_question_group_key(question, index)
        raw_areas = question.get("areas")
        areas = raw_areas if isinstance(raw_areas, list) else []
        clean_areas = [area for area in areas if isinstance(area, dict)]
        if key not in positions:
            grouped_question = dict(question)
            grouped_question["areas"] = list(clean_areas)
            positions[key] = len(grouped)
            grouped.append(grouped_question)
            continue
        grouped[positions[key]]["areas"].extend(clean_areas)
    return grouped


def _dummy_full_marks_result(
    question: dict[str, Any],
    *,
    mode: str,
    image_count: int = 0,
) -> dict[str, Any]:
    return {
        "marks": [step["max_marks"] for step in question["steps"]],
        "reasoning": f"Dummy {mode} assigned full marks for testing.",
        "raw_response": {
            "mode": "dummy_full_marks",
            "image_count": image_count,
        },
    }


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
    ai_evaluator: Callable[[str, str | list[str]], dict[str, Any]] | None = None,
    ai_vision_run_dir: Path = AI_VISION_RUN_DIR,
    cornerstone_submitter: Callable[..., dict[str, Any]] | None = None,
    agent_image_fetcher: Callable[[str], tuple[bytes, str]] | None = None,
    cornerstone_status_fetcher: Callable[..., dict[str, Any]] | None = None,
    agent_dummy_full_marks: bool = AGENT_DUMMY_FULL_MARKS,
    agent_job_run_dir: Path = AGENT_JOB_RUN_DIR,
) -> FastAPI:
    evaluate_image = ai_evaluator or (
        lambda prompt, image_path: evaluate_answer(
            question=prompt,
            image_path=image_path,
        )
    )
    submit_extraction = cornerstone_submitter or submit_cornerstone_job
    fetch_enhanced_image = agent_image_fetcher or fetch_agent_image
    fetch_extraction_status = cornerstone_status_fetcher or fetch_cornerstone_status

    def write_agent_artifact(
        agent_job_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> None:
        safe_name = "".join(
            character if character.isalnum() or character in {"-", "_"} else "-"
            for character in name.strip().lower()
        ).strip("-") or "payload"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        try:
            job_dir = agent_job_run_dir / agent_job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            artifact = {
                "agent_job_id": agent_job_id,
                "name": safe_name,
                "stored_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            (job_dir / f"{timestamp}-{safe_name}.json").write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            (job_dir / "latest.json").write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    def agent_response(evaluation_id: str) -> dict[str, Any]:
        job = database.get_agent_job_for_evaluation(evaluation_id)
        if not job:
            return {"enabled": False, "reviews": []}
        return {"enabled": True, **job}

    def revive_ignored_cornerstone_job(job: dict[str, Any]) -> dict[str, Any]:
        if job.get("status") != "ignored" or not job.get("cornerstone_job_id"):
            return job
        database.update_agent_job(
            job["id"],
            status="extracting",
            clear_error=True,
            clear_completed_at=True,
        )
        return database.get_agent_job_by_id(job["id"]) or {
            **job,
            "status": "extracting",
            "error": None,
            "completed_at": None,
        }

    async def start_agent_job(agent_job_id: str) -> None:
        pages = database.get_agent_job_pages(agent_job_id)
        if not pages:
            database.update_agent_job(
                agent_job_id,
                status="failed",
                error="No answer-sheet pages were found",
                completed=True,
            )
            return
        try:
            result = await asyncio.to_thread(
                submit_extraction,
                base_url=CORNERSTONE_API_URL,
                pages=pages,
                webhook_url=f"{PUBLIC_API_URL}/agent-jobs/cornerstone/webhook",
                webhook_secret=CORNERSTONE_WEBHOOK_SECRET,
            )
            cornerstone_job_id = str(result.get("job_id", "")).strip()
            if not cornerstone_job_id:
                raise ValueError("Cornerstone did not return a job_id")
            write_agent_artifact(agent_job_id, "cornerstone-submit", result)
            database.update_agent_job(
                agent_job_id,
                status="extracting",
                cornerstone_job_id=cornerstone_job_id,
                cornerstone_status_url=result.get("status_url"),
                clear_error=True,
            )
        except Exception as exc:
            database.update_agent_job(
                agent_job_id,
                status="failed",
                error=f"Cornerstone submission failed: {exc}",
                completed=True,
            )

    async def evaluate_agent_job(
        agent_job_id: str,
        cornerstone_questions: list[dict[str, Any]],
    ) -> None:
        job = database.get_agent_job_by_id(agent_job_id)
        if not job:
            return
        try:
            reviews = database.prepare_agent_reviews(
                agent_job_id,
                cornerstone_questions,
            )
        except Exception as exc:
            database.update_agent_job(
                agent_job_id,
                status="failed",
                error=f"Unable to map Cornerstone questions: {exc}",
                completed=True,
            )
            return

        ready_count = 0
        for index, review in enumerate(reviews, start=1):
            run_dir: Path | None = None
            metadata: dict[str, Any] = {}
            try:
                question = database.get_question(
                    job["evaluation_id"],
                    review["question_id"],
                )
                if not question:
                    raise LookupError("Mapped question was not found")
                if not review["page_id"]:
                    raise ValueError("Question did not map to an uploaded page")
                if not agent_dummy_full_marks and not review["area_urls"]:
                    raise ValueError("Cornerstone returned no enhanced answer segments")

                database.update_agent_review(review["id"], status="evaluating")
                run_id = database.new_id("run")
                run_dir = ai_vision_run_dir / run_id
                run_dir.mkdir(parents=True, exist_ok=False)
                image_paths: list[Path] = []
                for area_index, image_url in enumerate(review["area_urls"], start=1):
                    try:
                        image_bytes, content_type = await asyncio.to_thread(
                            fetch_enhanced_image,
                            image_url,
                        )
                        if not image_bytes:
                            raise ValueError(
                                f"Enhanced answer segment {area_index} was empty"
                            )
                    except Exception:
                        if agent_dummy_full_marks:
                            continue
                        raise
                    suffix = {
                        "image/jpeg": ".jpg",
                        "image/png": ".png",
                        "image/webp": ".webp",
                    }.get(content_type.split(";")[0].lower(), ".png")
                    image_path = run_dir / f"answer-segment-{area_index:03d}{suffix}"
                    image_path.write_bytes(image_bytes)
                    image_paths.append(image_path)

                prompt = build_evaluation_prompt(
                    question_text=question["question_text"],
                    reference_solution=question["reference_solution"],
                    steps=question["steps"],
                )
                bbox = review["bbox"] or {"x": 0, "y": 0, "w": 1, "h": 1}
                metadata = {
                    "run_id": run_id,
                    "source": "agent",
                    "agent_job_id": agent_job_id,
                    "agent_review_id": review["id"],
                    "evaluation_id": job["evaluation_id"],
                    "question_id": question["question_id"],
                    "question_no": question["question_no"],
                    "page_id": review["page_id"],
                    "content_type": "image/png",
                    "image_urls": review["area_urls"],
                    "selection": {
                        "x": bbox["x"],
                        "y": bbox["y"],
                        "width": bbox["w"],
                        "height": bbox["h"],
                    },
                    "status": "running",
                }
                (run_dir / "context.txt").write_text(
                    "\n\n".join(
                        (
                            f"Run ID:\n{run_id}",
                            f"Model:\n{MODEL}",
                            "Enhanced images available for AI Vision:\n"
                            + (
                                "\n".join(
                                    str(path.resolve()) for path in image_paths
                                )
                                if image_paths
                                else "none"
                            ),
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
                if agent_dummy_full_marks:
                    result = _dummy_full_marks_result(
                        question,
                        mode="agent mode",
                        image_count=len(image_paths),
                    )
                else:
                    image_input: str | list[str] = (
                        str(image_paths[0])
                        if len(image_paths) == 1
                        else [str(path) for path in image_paths]
                    )
                    result = await asyncio.to_thread(
                        evaluate_image,
                        prompt,
                        image_input,
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
                (run_dir / "result.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "marks": marks,
                            "reasoning": reasoning,
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                metadata["status"] = "ready"
                (run_dir / "metadata.json").write_text(
                    json.dumps(metadata, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                database.update_agent_review(
                    review["id"],
                    status="ready",
                    run_id=run_id,
                    marks=marks,
                    awarded_marks=sum(marks),
                )
                ready_count += 1
            except Exception as exc:
                if run_dir is not None:
                    _record_run_error(run_dir, metadata, exc)
                database.update_agent_review(
                    review["id"],
                    status="error",
                    error=str(exc),
                )
            finally:
                database.update_agent_job(
                    agent_job_id,
                    processed_questions=index,
                )

        database.update_agent_job(
            agent_job_id,
            status="ready" if ready_count or not reviews else "failed",
            error=(
                None
                if ready_count == len(reviews)
                else f"{len(reviews) - ready_count} question evaluations failed"
            ),
            completed=True,
        )

    def extract_cornerstone_result(
        payload: dict[str, Any],
    ) -> tuple[
        str,
        int,
        list[dict[str, Any]],
        list[dict[str, Any]],
        str | None,
    ]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        status_value = str(
            result.get("status")
            or data.get("status")
            or payload.get("status")
            or ""
        ).lower()
        if status_value == "failed":
            error = (
                result.get("error")
                or data.get("error")
                or payload.get("error")
                or "Cornerstone job failed"
            )
            return "failed", 0, [], [], str(error)
        if status_value != "done":
            return "processing", 0, [], [], None

        pages = result.get("pages") or []
        questions = result.get("questions") or []
        pages = [page for page in pages if isinstance(page, dict)]
        questions = [question for question in questions if isinstance(question, dict)]
        raw_question_count = len(questions)
        questions = _group_cornerstone_question_segments(questions)
        detected_raw = (
            result.get("question_count")
            or result.get("detected_questions")
            or data.get("question_count")
        )
        try:
            detected = int(detected_raw) if detected_raw is not None else len(questions)
        except (TypeError, ValueError):
            detected = len(questions)
        if len(questions) < raw_question_count and detected == raw_question_count:
            detected = len(questions)
        return "done", detected, pages, questions, None

    async def process_cornerstone_payload(
        job: dict[str, Any],
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
        *,
        artifact_name: str,
    ) -> None:
        write_agent_artifact(job["id"], artifact_name, payload)
        state, detected_questions, pages, questions, error = extract_cornerstone_result(
            payload
        )
        if state == "processing":
            return
        if state == "failed":
            database.update_agent_job(
                job["id"],
                status="failed",
                error=error or "Cornerstone job failed",
                completed=True,
            )
            return

        selected_questions = questions[: job["expected_questions"]]
        try:
            database.update_agent_page_images(
                job["evaluation_id"],
                pages,
                selected_questions,
            )
        except Exception as exc:
            database.update_agent_job(
                job["id"],
                status="failed",
                error=f"Unable to store enhanced page images: {exc}",
                completed=True,
            )
            return
        database.update_agent_job(
            job["id"],
            status="evaluating",
            detected_questions=detected_questions,
            clear_error=True,
        )
        background_tasks.add_task(evaluate_agent_job, job["id"], selected_questions)

    def finish_agent_job_if_decided(evaluation_id: str) -> None:
        job = database.get_agent_job_for_evaluation(evaluation_id)
        if not job:
            return
        pending = {
            "queued",
            "evaluating",
            "ready",
        }
        if job["reviews"] and not any(
            review["status"] in pending for review in job["reviews"]
        ):
            database.update_agent_job(job["id"], status="completed", completed=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.AGENT_JOB_RUN_DIR = agent_job_run_dir
        database.initialize_database()
        ai_vision_run_dir.mkdir(parents=True, exist_ok=True)
        agent_job_run_dir.mkdir(parents=True, exist_ok=True)
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
        background_tasks: BackgroundTasks,
        student_id: Annotated[str, Form(min_length=1)],
        paper_code: Annotated[str, Form(min_length=1)],
        images: Annotated[list[UploadFile], File(min_length=1)],
        student_name: Annotated[str | None, Form()] = None,
        assigned_evaluator_id: Annotated[str, Form()] = "eval_001",
        evaluation_batch: Annotated[str, Form()] = "Default",
        agent_mode: Annotated[bool, Form()] = False,
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
            evaluation = database.create_submission(
                student_id=student_id.strip(),
                student_name=student_name.strip() if student_name else None,
                paper_code=paper_code.strip(),
                assigned_evaluator_id=assigned_evaluator_id.strip(),
                evaluation_batch=evaluation_batch.strip(),
                pages=saved_pages,
                agent_mode=agent_mode,
            )
            if agent_mode:
                agent_job = database.get_agent_job_for_evaluation(
                    evaluation["evaluation_id"]
                )
                if agent_job:
                    background_tasks.add_task(start_agent_job, agent_job["id"])
            return evaluation
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

    @app.get("/evaluations/{evaluation_id}/agent")
    def get_agent_job(evaluation_id: str) -> dict[str, Any]:
        evaluation = database.get_evaluation(evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return agent_response(evaluation_id)

    @app.post("/evaluations/{evaluation_id}/agent/start")
    async def start_agent_for_evaluation(evaluation_id: str) -> dict[str, Any]:
        evaluation = database.get_evaluation(evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        try:
            job = database.ensure_agent_job(evaluation_id)
            database.reset_agent_job_for_start(job["id"])
            await start_agent_job(job["id"])
            return agent_response(evaluation_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/evaluations/{evaluation_id}/agent/sync")
    async def sync_agent_for_evaluation(
        evaluation_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        evaluation = database.get_evaluation(evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        job = database.get_agent_job_for_evaluation(evaluation_id)
        if not job:
            return {"enabled": False, "reviews": []}
        job = revive_ignored_cornerstone_job(job)
        if job.get("status") != "extracting" or not job.get("cornerstone_job_id"):
            return {"enabled": True, **job}
        try:
            payload = await asyncio.to_thread(
                fetch_extraction_status,
                base_url=CORNERSTONE_API_URL,
                job_id=job["cornerstone_job_id"],
                status_url=job.get("cornerstone_status_url"),
            )
            await process_cornerstone_payload(
                job,
                payload,
                background_tasks,
                artifact_name="cornerstone-sync",
            )
            return agent_response(evaluation_id)
        except Exception as exc:
            database.update_agent_job(
                job["id"],
                status="failed",
                error=f"Cornerstone status polling failed: {exc}",
                completed=True,
            )
            return agent_response(evaluation_id)

    @app.post("/agent-jobs/cornerstone/webhook", status_code=204)
    @app.post("/api/cornerstone/webhook", status_code=204)
    async def cornerstone_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> Response:
        body = await request.body()
        supplied_signature = request.headers.get("X-Cornerstone-Signature", "")
        if CORNERSTONE_WEBHOOK_SECRET and not valid_cornerstone_signature(
            body,
            supplied_signature,
            CORNERSTONE_WEBHOOK_SECRET,
        ):
            raise HTTPException(status_code=401, detail="Invalid Cornerstone signature")
        try:
            event = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid Cornerstone webhook JSON",
            ) from exc

        cornerstone_job_id = str(event.get("job_id", "")).strip()
        if not cornerstone_job_id and isinstance(event.get("data"), dict):
            cornerstone_job_id = str(event["data"].get("job_id", "")).strip()
            if not cornerstone_job_id and isinstance(event["data"].get("result"), dict):
                cornerstone_job_id = str(
                    event["data"]["result"].get("job_id", "")
                ).strip()
        if not cornerstone_job_id and isinstance(event.get("result"), dict):
            cornerstone_job_id = str(event["result"].get("job_id", "")).strip()
        job = database.get_agent_job_by_cornerstone_id(cornerstone_job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Agent job not found")
        await process_cornerstone_payload(
            job,
            event,
            background_tasks,
            artifact_name="cornerstone-webhook",
        )
        return Response(status_code=204)

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
            if agent_dummy_full_marks:
                result = _dummy_full_marks_result(
                    question,
                    mode="AI Vision",
                    image_count=1,
                )
            else:
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

    @app.post(
        "/evaluations/{evaluation_id}/agent/reviews/{review_id}/accept"
    )
    def accept_agent_review(
        evaluation_id: str,
        review_id: str,
    ) -> dict[str, Any]:
        review = database.get_agent_review(evaluation_id, review_id)
        if not review:
            raise HTTPException(status_code=404, detail="Agent review not found")
        if review["status"] != "ready" or not review["run_id"]:
            raise HTTPException(
                status_code=409,
                detail="Agent review is not ready for acceptance",
            )
        question = database.get_question(evaluation_id, review["question_id"])
        if not question or not review["page_id"]:
            raise HTTPException(status_code=404, detail="Mapped question was not found")
        try:
            metadata, run_result = _load_ai_vision_run(
                ai_vision_run_dir,
                review["run_id"],
                evaluation_id,
            )
            marks = normalize_step_marks(
                run_result.get("marks", review["marks"]),
                [step["max_marks"] for step in question["steps"]],
            )
            selection = metadata.get("selection", {})
            result = database.accept_ai_vision_marks(
                evaluation_id,
                question_id=review["question_id"],
                page_id=review["page_id"],
                marks=marks,
                x=float(selection.get("x", 0)),
                y=float(selection.get("y", 0)),
                width=float(selection.get("width", 1)),
                height=float(selection.get("height", 1)),
                reasoning=str(run_result.get("reasoning", "")).strip(),
            )
            _write_run_decision(
                ai_vision_run_dir,
                review["run_id"],
                evaluation_id,
                "accepted",
            )
            database.update_agent_review(review_id, status="accepted")
            finish_agent_job_if_decided(evaluation_id)
            return {
                **result,
                "agent": {
                    "enabled": True,
                    **(database.get_agent_job_for_evaluation(evaluation_id) or {}),
                },
            }
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/evaluations/{evaluation_id}/agent/reviews/{review_id}/reject"
    )
    def reject_agent_review(
        evaluation_id: str,
        review_id: str,
    ) -> dict[str, Any]:
        review = database.get_agent_review(evaluation_id, review_id)
        if not review:
            raise HTTPException(status_code=404, detail="Agent review not found")
        if review["status"] != "ready" or not review["run_id"]:
            raise HTTPException(
                status_code=409,
                detail="Agent review is not ready for rejection",
            )
        try:
            _write_run_decision(
                ai_vision_run_dir,
                review["run_id"],
                evaluation_id,
                "rejected",
            )
            database.update_agent_review(review_id, status="rejected")
            finish_agent_job_if_decided(evaluation_id)
            return {
                "status": "rejected",
                "agent": {
                    "enabled": True,
                    **(database.get_agent_job_for_evaluation(evaluation_id) or {}),
                },
            }
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
