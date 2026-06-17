from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import database
from app.main import create_app


PAPER = {
    "paper_code": "MATH-1-A",
    "subject_code": "MATH",
    "subject_name": "Mathematics",
    "class_code": "1",
    "questions": [
        {
            "question_no": "Q1",
            "question_text": "What is 1 + 1?",
            "max_marks": 1,
            "display_order": 1,
            "steps": [
                {
                    "step_no": 1,
                    "title": "Answer",
                    "description": "The answer is 2.",
                    "max_marks": 1,
                }
            ],
        }
    ],
}


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.root = root
        database.DATABASE_PATH = root / "test.db"
        database.UPLOAD_DIR = root / "uploads"
        self.cornerstone_requests: list[dict] = []
        self.cornerstone_status_requests: list[dict] = []
        self.cornerstone_status_payloads: list[dict] = []
        self.fetched_agent_images: list[str] = []

        def submit_cornerstone(**kwargs):
            self.cornerstone_requests.append(kwargs)
            job_id = f"cornerstone-{len(self.cornerstone_requests)}"
            return {
                "job_id": job_id,
                "status": "processing",
                "status_url": f"http://localhost:8001/v1/jobs/{job_id}",
            }

        def fetch_agent_image(url: str) -> tuple[bytes, str]:
            self.fetched_agent_images.append(url)
            return b"enhanced-answer-segment", "image/png"

        def fetch_cornerstone_status(**kwargs):
            self.cornerstone_status_requests.append(kwargs)
            if not self.cornerstone_status_payloads:
                return {"status": "processing"}
            return self.cornerstone_status_payloads.pop(0)

        self.ai_evaluator_calls = 0

        def evaluate_ai(_prompt, _image_path):
            self.ai_evaluator_calls += 1
            return {
                "marks": [0.75, 99],
                "reasoning": "The submitted answer satisfies the criterion.",
            }

        self.client_context = TestClient(
            create_app(
                seed_data=False,
                ai_evaluator=evaluate_ai,
                ai_vision_dummy_delay_seconds=0,
                ai_vision_run_dir=root / "ai_vision",
                agent_job_run_dir=root / "agent_jobs",
                cornerstone_submitter=submit_cornerstone,
                agent_image_fetcher=fetch_agent_image,
                cornerstone_status_fetcher=fetch_cornerstone_status,
            )
        )
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_create_submission_mark_and_submit(self) -> None:
        paper_response = self.client.post("/question-papers", json=PAPER)
        self.assertEqual(paper_response.status_code, 201)

        submission_response = self.client.post(
            "/submissions",
            data={
                "student_id": "STU-1",
                "student_name": "Test Student",
                "paper_code": "MATH-1-A",
            },
            files=[
                (
                    "images",
                    ("answer.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
                )
            ],
        )
        self.assertEqual(submission_response.status_code, 201)
        evaluation_id = submission_response.json()["evaluation_id"]

        question = self.client.get(
            f"/evaluations/{evaluation_id}/questions"
        ).json()[0]
        detail = self.client.get(
            f"/evaluations/{evaluation_id}/questions/{question['question_id']}"
        ).json()
        step = detail["steps"][0]

        invalid_mark = self.client.post(
            f"/evaluations/{evaluation_id}/steps/{step['step_id']}/marks",
            json={"awarded_marks": 2},
        )
        self.assertEqual(invalid_mark.status_code, 422)

        mark_response = self.client.post(
            f"/evaluations/{evaluation_id}/steps/{step['step_id']}/marks",
            json={"awarded_marks": 1},
        )
        self.assertEqual(mark_response.status_code, 200)
        self.assertEqual(mark_response.json()["status"], "Completed")

        pages = self.client.get(f"/evaluations/{evaluation_id}/pages").json()
        annotation_response = self.client.post(
            f"/evaluations/{evaluation_id}/annotations",
            json={
                "question_id": question["question_id"],
                "step_id": step["step_id"],
                "page_id": pages[0]["page_id"],
                "text": "Q1 · 1/1",
                "x": 0.25,
                "y": 0.35,
                "width": 0.12,
                "height": 0.06,
            },
        )
        self.assertEqual(annotation_response.status_code, 201)
        annotation_id = annotation_response.json()["annotation_id"]
        resize_response = self.client.patch(
            f"/evaluations/{evaluation_id}/annotations/{annotation_id}",
            json={"width": 0.2, "height": 0.1},
        )
        self.assertEqual(resize_response.status_code, 200)
        self.assertEqual(resize_response.json()["width"], 0.2)

        ai_response = self.client.post(
            f"/evaluations/{evaluation_id}/ai-vision",
            data={
                "question_id": question["question_id"],
                "page_id": pages[0]["page_id"],
                "x": "0.1",
                "y": "0.2",
                "width": "0.4",
                "height": "0.2",
            },
            files=[
                (
                    "crop",
                    ("selection.png", b"dummy-image-bytes", "image/png"),
                )
            ],
        )
        self.assertEqual(ai_response.status_code, 201)
        self.assertEqual(ai_response.json()["marks"], [1.0])
        self.assertEqual(ai_response.json()["awarded_marks"], 1.0)
        self.assertEqual(self.ai_evaluator_calls, 0)
        run_id = ai_response.json()["run_id"]
        run_dir = self.root / "ai_vision" / run_id
        self.assertEqual(
            (run_dir / "answer-selection.png").read_bytes(),
            b"dummy-image-bytes",
        )
        context = (run_dir / "context.txt").read_text("utf-8")
        self.assertIn("What is 1 + 1?", context)
        self.assertIn("Answer: The answer is 2. (max 1)", context)
        self.assertEqual(
            json.loads((run_dir / "result.json").read_text("utf-8"))["marks"],
            [1.0],
        )

        accept_ai_response = self.client.post(
            f"/evaluations/{evaluation_id}/ai-vision/accept",
            json={
                "run_id": run_id,
                "question_id": question["question_id"],
                "page_id": pages[0]["page_id"],
                "marks": ai_response.json()["marks"],
                "x": 0.1,
                "y": 0.2,
                "width": 0.4,
                "height": 0.2,
            },
        )
        self.assertEqual(accept_ai_response.status_code, 200)
        self.assertEqual(
            accept_ai_response.json()["question"]["awarded_marks"],
            1.0,
        )
        self.assertEqual(
            json.loads((run_dir / "metadata.json").read_text("utf-8"))[
                "decision"
            ],
            "accepted",
        )
        hidden_notes = database.list_ai_vision_notes(evaluation_id)
        self.assertEqual(len(hidden_notes or []), 1)
        self.assertIn("Dummy AI Vision", hidden_notes[0]["analysis"])
        self.assertTrue(
            accept_ai_response.json()["annotation"]["text"].startswith("TAI|")
        )
        self.assertAlmostEqual(
            accept_ai_response.json()["annotation"]["x"],
            0.3,
        )
        self.assertAlmostEqual(
            accept_ai_response.json()["annotation"]["y"],
            0.3,
        )
        self.assertEqual(
            self.client.get(
                f"/evaluations/{evaluation_id}/questions/"
                f"{question['question_id']}"
            ).json()["steps"][0]["awarded_marks"],
            1.0,
        )

        reset_response = self.client.delete(
            f"/evaluations/{evaluation_id}/questions/{question['question_id']}/marks"
        )
        self.assertEqual(reset_response.status_code, 200)
        self.assertEqual(reset_response.json()["status"], "Not Started")
        self.assertEqual(
            self.client.get(f"/evaluations/{evaluation_id}/annotations").json(),
            [],
        )

        self.client.post(
            f"/evaluations/{evaluation_id}/steps/{step['step_id']}/marks",
            json={"awarded_marks": 1},
        )
        submit_response = self.client.post(f"/evaluations/{evaluation_id}/submit")
        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(submit_response.json()["status"], "Completed")

    def test_rejects_paper_when_step_marks_do_not_match(self) -> None:
        invalid_paper = {
            **PAPER,
            "paper_code": "INVALID",
            "questions": [
                {
                    **PAPER["questions"][0],
                    "max_marks": 2,
                }
            ],
        }
        response = self.client.post("/question-papers", json=invalid_paper)
        self.assertEqual(response.status_code, 422)

    def _cornerstone_webhook(
        self,
        payload: dict,
        path: str = "/agent-jobs/cornerstone/webhook",
    ) -> object:
        body = json.dumps(payload).encode()
        signature = hmac.new(
            b"sheldon-local-agent",
            body,
            hashlib.sha256,
        ).hexdigest()
        return self.client.post(
            path,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Cornerstone-Signature": f"sha256={signature}",
            },
        )

    def test_agent_mode_builds_review_and_accepts_marks(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-1",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        )
        self.assertEqual(submission.status_code, 201)
        evaluation_id = submission.json()["evaluation_id"]
        self.assertTrue(submission.json()["agent_mode"])
        self.assertEqual(len(self.cornerstone_requests), 1)
        self.assertEqual(
            self.cornerstone_requests[0]["webhook_url"],
            "http://localhost:8000/agent-jobs/cornerstone/webhook",
        )

        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 1,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.1,
                                            "y1": 0.2,
                                            "width": 0.8,
                                            "height": 0.3,
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)
        agent = self.client.get(f"/evaluations/{evaluation_id}/agent").json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["processed_questions"], 1)
        self.assertEqual(agent["ready_questions"], 1)
        review = agent["reviews"][0]
        self.assertEqual(review["marks"], [1.0])
        self.assertEqual(review["area_count"], 1)
        self.assertIn("space=enhanced", review["enhanced_image_url"])
        self.assertEqual(len(self.fetched_agent_images), 1)

        run_dir = self.root / "ai_vision" / review["run_id"]
        self.assertEqual(
            (run_dir / "answer-segment-001.png").read_bytes(),
            b"enhanced-answer-segment",
        )
        accept = self.client.post(
            f"/evaluations/{evaluation_id}/agent/reviews/{review['id']}/accept"
        )
        self.assertEqual(accept.status_code, 200)
        self.assertEqual(accept.json()["question"]["awarded_marks"], 1.0)
        self.assertTrue(accept.json()["agent"]["enabled"])
        self.assertEqual(accept.json()["agent"]["status"], "completed")
        self.assertEqual(accept.json()["agent"]["accepted_questions"], 1)

    def test_cornerstone_webhook_alias_updates_agent_job(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-WEBHOOK-ALIAS",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()

        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "result": {
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                }
                            ],
                        }
                    ],
                },
            },
            path="/api/cornerstone/webhook",
        )
        self.assertEqual(webhook.status_code, 204)
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["ready_questions"], 1)

    def test_agent_start_api_creates_cornerstone_job_for_existing_submission(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-START",
                "paper_code": "MATH-1-A",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        self.assertFalse(submission["agent_mode"])
        self.assertEqual(len(self.cornerstone_requests), 0)

        start = self.client.post(
            f"/evaluations/{submission['evaluation_id']}/agent/start"
        )
        self.assertEqual(start.status_code, 200)
        body = start.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["status"], "extracting")
        self.assertEqual(body["cornerstone_job_id"], "cornerstone-1")
        self.assertEqual(
            body["cornerstone_status_url"],
            "http://localhost:8001/v1/jobs/cornerstone-1",
        )
        self.assertEqual(len(self.cornerstone_requests), 1)

    def test_agent_sync_polls_cornerstone_status_without_webhook_body(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-SYNC",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        self.cornerstone_status_payloads.append(
            {
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "job_id": "cornerstone-1",
                    "status": "done",
                    "question_count": 1,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.2,
                                            "y1": 0.25,
                                            "width": 0.5,
                                            "height": 0.3,
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        )

        sync = self.client.post(
            f"/evaluations/{submission['evaluation_id']}/agent/sync"
        )
        self.assertEqual(sync.status_code, 200)
        self.assertEqual(len(self.cornerstone_status_requests), 1)
        self.assertEqual(
            self.cornerstone_status_requests[0]["status_url"],
            "http://localhost:8001/v1/jobs/cornerstone-1",
        )
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["reviews"][0]["marks"], [1.0])

    def test_agent_sync_recovers_legacy_ignored_cornerstone_job(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-IGNORED",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        database.update_agent_job(
            agent["id"],
            status="ignored",
            error="Expected 5 questions but Cornerstone detected 2; agent grading was skipped",
            completed=True,
        )
        self.cornerstone_status_payloads.append(
            {
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 2,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                }
                            ],
                        },
                        {
                            "question_no": 2,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/2/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                }
                            ],
                        },
                    ],
                },
            }
        )

        sync = self.client.post(
            f"/evaluations/{submission['evaluation_id']}/agent/sync"
        )

        self.assertEqual(sync.status_code, 200)
        body = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(body["status"], "ready")
        self.assertIsNone(body["error"])
        self.assertEqual(body["detected_questions"], 2)
        self.assertEqual(body["processed_questions"], 1)
        self.assertEqual(body["ready_questions"], 1)
        self.assertEqual(body["reviews"][0]["marks"], [1.0])

    def test_agent_sync_reads_nested_result_and_uses_enhanced_page_image(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-RESULT",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        enhanced_page_url = (
            "http://localhost:8001/v1/jobs/cornerstone-1/pages/1/image"
            "?space=enhanced"
        )
        self.cornerstone_status_payloads.append(
            {
                "job_id": "cornerstone-1",
                "status": "done",
                "result": {
                    "pages": [
                        {
                            "page_index": 1,
                            "image_url": enhanced_page_url,
                            "width": 1234,
                            "height": 5678,
                        }
                    ],
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "page_image_url": enhanced_page_url,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.1,
                                            "y1": 0.2,
                                            "x2": 0.7,
                                            "y2": 0.6,
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        )

        sync = self.client.post(
            f"/evaluations/{submission['evaluation_id']}/agent/sync"
        )
        self.assertEqual(sync.status_code, 200)
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["detected_questions"], 1)
        self.assertAlmostEqual(agent["reviews"][0]["bbox"]["w"], 0.6)
        self.assertAlmostEqual(agent["reviews"][0]["bbox"]["h"], 0.4)

        pages = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/pages"
        ).json()
        self.assertEqual(pages[0]["image_url"], enhanced_page_url)
        self.assertEqual(pages[0]["image_space"], "enhanced")
        self.assertEqual(pages[0]["width"], 1234)
        self.assertEqual(pages[0]["height"], 5678)

        artifact_dir = self.root / "agent_jobs" / agent["id"]
        self.assertTrue((artifact_dir / "latest.json").exists())
        self.assertTrue(
            any(path.name.endswith("-cornerstone-submit.json") for path in artifact_dir.iterdir())
        )
        self.assertTrue(
            any(path.name.endswith("-cornerstone-sync.json") for path in artifact_dir.iterdir())
        )

    def test_agent_review_returns_display_areas_across_page_boundary(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-MULTIPAGE",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer-1.png", b"original-page-1", "image/png"),
                ),
                (
                    "images",
                    ("answer-2.png", b"original-page-2", "image/png"),
                ),
            ],
        ).json()
        pages = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/pages"
        ).json()

        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 1,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.15,
                                            "y1": 0.82,
                                            "width": 0.5,
                                            "height": 0.36,
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)

        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        review = agent["reviews"][0]
        self.assertAlmostEqual(review["bbox"]["y"], 0.82)
        self.assertAlmostEqual(review["bbox"]["h"], 0.18)
        self.assertEqual(len(review["areas"]), 2)
        self.assertEqual(review["areas"][0]["page_id"], pages[0]["page_id"])
        self.assertEqual(review["areas"][1]["page_id"], pages[1]["page_id"])
        self.assertAlmostEqual(review["areas"][0]["bbox"]["y"], 0.82)
        self.assertAlmostEqual(review["areas"][0]["bbox"]["h"], 0.18)
        self.assertAlmostEqual(review["areas"][1]["bbox"]["y"], 0)
        self.assertAlmostEqual(review["areas"][1]["bbox"]["h"], 0.18)

    def test_agent_review_returns_each_detected_area_across_pages(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-EXPLICIT-MULTIPAGE",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer-1.png", b"original-page-1", "image/png"),
                ),
                (
                    "images",
                    ("answer-2.png", b"original-page-2", "image/png"),
                ),
            ],
        ).json()
        pages = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/pages"
        ).json()

        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 1,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.1,
                                            "y1": 0.72,
                                            "width": 0.8,
                                            "height": 0.28,
                                        }
                                    },
                                },
                                {
                                    "page_index": 2,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/2/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.12,
                                            "y1": 0.0,
                                            "width": 0.76,
                                            "height": 0.24,
                                        }
                                    },
                                },
                            ],
                        }
                    ],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)

        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        review = agent["reviews"][0]
        self.assertEqual(len(review["areas"]), 2)
        self.assertEqual(review["areas"][0]["page_id"], pages[0]["page_id"])
        self.assertEqual(review["areas"][1]["page_id"], pages[1]["page_id"])
        self.assertAlmostEqual(review["areas"][0]["bbox"]["y"], 0.72)
        self.assertAlmostEqual(review["areas"][0]["bbox"]["h"], 0.28)
        self.assertAlmostEqual(review["areas"][1]["bbox"]["y"], 0.0)
        self.assertAlmostEqual(review["areas"][1]["bbox"]["h"], 0.24)

    def test_agent_mode_groups_duplicate_question_segments(self) -> None:
        paper = {
            **PAPER,
            "paper_code": "MATH-DUPLICATE-SEGMENTS",
            "questions": [
                {
                    **PAPER["questions"][0],
                    "question_no": "Q1",
                    "display_order": 1,
                },
                {
                    **PAPER["questions"][0],
                    "question_no": "Q2",
                    "display_order": 2,
                },
            ],
        }
        self.assertEqual(
            self.client.post("/question-papers", json=paper).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-DUPLICATE-SEGMENTS",
                "paper_code": "MATH-DUPLICATE-SEGMENTS",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()

        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 3,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.1,
                                            "y1": 0.1,
                                            "width": 0.8,
                                            "height": 0.2,
                                        }
                                    },
                                }
                            ],
                        },
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/2/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.12,
                                            "y1": 0.42,
                                            "width": 0.76,
                                            "height": 0.18,
                                        }
                                    },
                                }
                            ],
                        },
                        {
                            "question_no": 2,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/2/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.1,
                                            "y1": 0.7,
                                            "width": 0.8,
                                            "height": 0.2,
                                        }
                                    },
                                }
                            ],
                        },
                    ],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)

        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["expected_questions"], 2)
        self.assertEqual(agent["detected_questions"], 2)
        self.assertEqual(agent["processed_questions"], 2)
        self.assertEqual(agent["ready_questions"], 2)
        self.assertEqual(
            [review["question_no"] for review in agent["reviews"]],
            ["Q1", "Q2"],
        )

        first_review, second_review = agent["reviews"]
        self.assertEqual(first_review["cornerstone_question_no"], 1)
        self.assertEqual(first_review["area_count"], 2)
        self.assertEqual(len(first_review["areas"]), 2)
        self.assertEqual(len(first_review["area_urls"]), 2)
        self.assertIn("questions/1/areas/1/image", first_review["area_urls"][0])
        self.assertIn("questions/1/areas/2/image", first_review["area_urls"][1])
        self.assertAlmostEqual(first_review["areas"][0]["bbox"]["y"], 0.1)
        self.assertAlmostEqual(first_review["areas"][1]["bbox"]["y"], 0.42)
        self.assertEqual(second_review["cornerstone_question_no"], 2)
        self.assertEqual(second_review["area_count"], 1)
        self.assertEqual(len(second_review["areas"]), 1)
        self.assertIn("questions/2/areas/1/image", second_review["area_urls"][0])
        self.assertEqual(len(self.fetched_agent_images), 3)

    def test_cornerstone_job_uses_ocr_enabled_mode(self) -> None:
        from app.agent_workflow import submit_cornerstone_job

        image_path = self.root / "page.png"
        image_path.write_bytes(b"page-image")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"job_id": "cornerstone-test"}

        with patch("app.agent_workflow.httpx.post", return_value=response) as post:
            result = submit_cornerstone_job(
                base_url="http://localhost:8001",
                pages=[
                    {
                        "original_filename": "page.png",
                        "stored_path": str(image_path),
                        "content_type": "image/png",
                    }
                ],
                webhook_url="http://localhost:8000/agent-jobs/cornerstone/webhook",
                webhook_secret="secret",
            )

        self.assertEqual(result["job_id"], "cornerstone-test")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["data"]["ocr_enabled"], "true")
        self.assertEqual(kwargs["data"]["coordinate_space"], "enhanced")
        self.assertEqual(kwargs["data"]["image_delivery"], "url")

    def test_agent_mode_uses_first_questions_when_cornerstone_returns_extra(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-COUNT",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 2,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                    "bbox": {
                                        "normalized": {
                                            "x1": 0.1,
                                            "y1": 0.2,
                                            "width": 0.8,
                                            "height": 0.3,
                                        }
                                    },
                                }
                            ],
                        },
                        {
                            "question_no": 2,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/2/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                }
                            ],
                        },
                    ],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["detected_questions"], 2)
        self.assertEqual(agent["processed_questions"], 1)
        self.assertEqual(agent["ready_questions"], 1)
        self.assertEqual(len(agent["reviews"]), 1)
        self.assertEqual(agent["reviews"][0]["cornerstone_question_no"], 1)
        self.assertEqual(agent["reviews"][0]["marks"], [1.0])

    def test_agent_mode_maps_partial_coordinates_and_leaves_rest_manual(self) -> None:
        paper = {
            **PAPER,
            "paper_code": "MATH-4-A",
            "questions": [
                {
                    **PAPER["questions"][0],
                    "question_no": f"Q{question_no}",
                    "display_order": question_no,
                }
                for question_no in range(1, 5)
            ],
        }
        self.assertEqual(
            self.client.post("/question-papers", json=paper).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-PARTIAL",
                "paper_code": "MATH-4-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 2,
                    "questions": [
                        {
                            "question_no": 1,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/1/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                }
                            ],
                        },
                        {
                            "question_no": 2,
                            "areas": [
                                {
                                    "page_index": 1,
                                    "question_image_url": (
                                        "http://localhost:8001/v1/jobs/"
                                        "cornerstone-1/questions/2/areas/1/image"
                                        "?space=enhanced"
                                    ),
                                }
                            ],
                        },
                    ],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["expected_questions"], 4)
        self.assertEqual(agent["detected_questions"], 2)
        self.assertEqual(agent["processed_questions"], 2)
        self.assertEqual(agent["ready_questions"], 2)
        self.assertEqual(
            [review["question_no"] for review in agent["reviews"]],
            ["Q1", "Q2"],
        )

    def test_agent_mode_allows_empty_cornerstone_coordinates(self) -> None:
        self.assertEqual(
            self.client.post("/question-papers", json=PAPER).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "AGENT-EMPTY",
                "paper_code": "MATH-1-A",
                "agent_mode": "true",
            },
            files=[
                (
                    "images",
                    ("answer.png", b"original-page", "image/png"),
                )
            ],
        ).json()
        webhook = self._cornerstone_webhook(
            {
                "event": "cornerstone.job.done",
                "job_id": "cornerstone-1",
                "status": "done",
                "data": {
                    "question_count": 0,
                    "questions": [],
                },
            }
        )
        self.assertEqual(webhook.status_code, 204)
        agent = self.client.get(
            f"/evaluations/{submission['evaluation_id']}/agent"
        ).json()
        self.assertEqual(agent["status"], "ready")
        self.assertEqual(agent["detected_questions"], 0)
        self.assertEqual(agent["processed_questions"], 0)
        self.assertEqual(agent["ready_questions"], 0)
        self.assertIsNone(agent["error"])
        self.assertEqual(agent["reviews"], [])

    def test_bulk_question_marking_stays_synchronized(self) -> None:
        paper = {
            **PAPER,
            "paper_code": "MATH-2-A",
            "questions": [
                {
                    **PAPER["questions"][0],
                    "max_marks": 2,
                    "steps": [
                        {
                            "step_no": 1,
                            "title": "Working",
                            "description": "Shows the working.",
                            "max_marks": 1,
                        },
                        {
                            "step_no": 2,
                            "title": "Answer",
                            "description": "Gives the final answer.",
                            "max_marks": 1,
                        },
                    ],
                }
            ],
        }
        self.assertEqual(
            self.client.post("/question-papers", json=paper).status_code,
            201,
        )
        submission = self.client.post(
            "/submissions",
            data={
                "student_id": "STU-2",
                "student_name": "Bulk Marking Student",
                "paper_code": "MATH-2-A",
            },
            files=[
                (
                    "images",
                    (
                        "answer.svg",
                        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                        "image/svg+xml",
                    ),
                )
            ],
        ).json()
        evaluation_id = submission["evaluation_id"]
        question = self.client.get(
            f"/evaluations/{evaluation_id}/questions"
        ).json()[0]
        detail = self.client.get(
            f"/evaluations/{evaluation_id}/questions/{question['question_id']}"
        ).json()
        first_step = detail["steps"][0]
        page = self.client.get(f"/evaluations/{evaluation_id}/pages").json()[0]

        self.client.post(
            f"/evaluations/{evaluation_id}/steps/{first_step['step_id']}/marks",
            json={"awarded_marks": 0.5},
        )
        self.client.post(
            f"/evaluations/{evaluation_id}/annotations",
            json={
                "question_id": question["question_id"],
                "step_id": first_step["step_id"],
                "page_id": page["page_id"],
                "text": "Q1 · S1 · 0.5/1",
                "x": 0.2,
                "y": 0.2,
                "width": 0.04,
                "height": 0.04,
            },
        )

        complete = self.client.post(
            f"/evaluations/{evaluation_id}/steps/"
            f"{detail['steps'][1]['step_id']}/marks",
            json={"awarded_marks": 0},
        )
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(
            [step["awarded_marks"] for step in complete.json()["steps"]],
            [0.5, 0],
        )
        self.assertEqual(complete.json()["status"], "Completed")

        full_marks = self.client.post(
            f"/evaluations/{evaluation_id}/questions/"
            f"{question['question_id']}/full-marks"
        )
        self.assertEqual(full_marks.status_code, 200)
        self.assertEqual(
            [step["awarded_marks"] for step in full_marks.json()["steps"]],
            [1, 1],
        )
        annotations = self.client.get(
            f"/evaluations/{evaluation_id}/annotations"
        ).json()
        self.assertEqual(annotations[0]["text"], "Q1 · S1 · 1/1")

        for awarded in (1, 2):
            total_text = f"T|Q1|1/1,1/1|{awarded}/2"
            self.assertLessEqual(len(total_text), 100)
            total_response = self.client.post(
                f"/evaluations/{evaluation_id}/annotations",
                json={
                    "question_id": question["question_id"],
                    "step_id": None,
                    "page_id": page["page_id"],
                    "text": total_text,
                    "x": 0.3,
                    "y": 0.3,
                    "width": 0.18,
                    "height": 0.12,
                },
            )
            self.assertEqual(total_response.status_code, 201)
        annotations = self.client.get(
            f"/evaluations/{evaluation_id}/annotations"
        ).json()
        totals = [item for item in annotations if item["step_id"] is None]
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0]["text"], "T|Q1|1/1,1/1|2/2")
        moved_total = self.client.patch(
            f"/evaluations/{evaluation_id}/annotations/"
            f"{totals[0]['annotation_id']}",
            json={"x": 0.55, "y": 0.65},
        )
        self.assertEqual(moved_total.status_code, 200)
        self.assertEqual(moved_total.json()["x"], 0.55)
        self.assertEqual(moved_total.json()["y"], 0.65)

        reset_paper = self.client.delete(
            f"/evaluations/{evaluation_id}/marks"
        )
        self.assertEqual(reset_paper.status_code, 200)
        self.assertEqual(reset_paper.json()["status"], "Not Started")
        self.assertEqual(reset_paper.json()["questions_evaluated"], 0)
        self.assertEqual(reset_paper.json()["total_marks"], 0)
        self.assertEqual(
            self.client.get(f"/evaluations/{evaluation_id}/annotations").json(),
            [],
        )
        reset_question = self.client.get(
            f"/evaluations/{evaluation_id}/questions/{question['question_id']}"
        ).json()
        self.assertTrue(
            all(step["awarded_marks"] is None for step in reset_question["steps"])
        )


if __name__ == "__main__":
    unittest.main()
