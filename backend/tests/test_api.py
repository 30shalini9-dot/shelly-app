from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        database.DATABASE_PATH = root / "test.db"
        database.UPLOAD_DIR = root / "uploads"
        self.client_context = TestClient(
            create_app(seed_data=False, ai_delay_seconds=0)
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
                "question_text": "What is 1 + 1?",
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
        self.assertIn("Dummy AI Vision review", ai_response.json()["analysis"])
        self.assertEqual(
            self.client.get(
                f"/evaluations/{evaluation_id}/ai-vision-notes"
            ).json(),
            [],
        )

        save_ai_response = self.client.post(
            f"/evaluations/{evaluation_id}/ai-vision-notes",
            json={
                key: value
                for key, value in ai_response.json().items()
                if key
                in {
                    "question_id",
                    "page_id",
                    "analysis",
                    "x",
                    "y",
                    "width",
                    "height",
                }
            },
        )
        self.assertEqual(save_ai_response.status_code, 201)
        saved_note_id = save_ai_response.json()["note_id"]
        self.assertEqual(
            len(
                self.client.get(
                    f"/evaluations/{evaluation_id}/ai-vision-notes"
                ).json()
            ),
            1,
        )
        delete_ai_response = self.client.delete(
            f"/evaluations/{evaluation_id}/ai-vision-notes/{saved_note_id}"
        )
        self.assertEqual(delete_ai_response.status_code, 204)
        self.assertEqual(
            self.client.get(
                f"/evaluations/{evaluation_id}/ai-vision-notes"
            ).json(),
            [],
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
