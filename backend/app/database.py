from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DATABASE_PATH, UPLOAD_DIR


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS question_papers (
    id TEXT PRIMARY KEY,
    paper_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    subject_code TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    class_code TEXT NOT NULL,
    total_questions INTEGER NOT NULL,
    maximum_marks REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    question_paper_id TEXT NOT NULL REFERENCES question_papers(id) ON DELETE CASCADE,
    question_no TEXT NOT NULL,
    question_text TEXT NOT NULL,
    max_marks REAL NOT NULL,
    question_type TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    reference_solution TEXT NOT NULL DEFAULT '',
    UNIQUE(question_paper_id, question_no),
    UNIQUE(question_paper_id, display_order)
);

CREATE TABLE IF NOT EXISTS question_steps (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    step_no INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    max_marks REAL NOT NULL,
    UNIQUE(question_id, step_no)
);

CREATE TABLE IF NOT EXISTS student_submissions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    student_name TEXT,
    question_paper_id TEXT NOT NULL REFERENCES question_papers(id),
    evaluation_status TEXT NOT NULL DEFAULT 'Not Started',
    assigned_evaluator_id TEXT NOT NULL,
    evaluation_batch TEXT NOT NULL DEFAULT 'Default',
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_pages (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES student_submissions(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    UNIQUE(submission_id, page_number)
);

CREATE TABLE IF NOT EXISTS submission_question_mappings (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES student_submissions(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id),
    page_id TEXT REFERENCES submission_pages(id),
    bbox_json TEXT,
    mapping_status TEXT NOT NULL DEFAULT 'mapped',
    is_manually_changed INTEGER NOT NULL DEFAULT 0,
    viewed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(submission_id, question_id)
);

CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL UNIQUE REFERENCES student_submissions(id) ON DELETE CASCADE,
    evaluator_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Not Started',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_step_marks (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL REFERENCES question_steps(id),
    awarded_marks REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(evaluation_id, step_id)
);

CREATE TABLE IF NOT EXISTS answer_annotations (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES question_steps(id) ON DELETE CASCADE,
    page_id TEXT NOT NULL REFERENCES submission_pages(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_vision_notes (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    page_id TEXT NOT NULL REFERENCES submission_pages(id) ON DELETE CASCADE,
    analysis TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_paper ON questions(question_paper_id);
CREATE INDEX IF NOT EXISTS idx_steps_question ON question_steps(question_id);
CREATE INDEX IF NOT EXISTS idx_pages_submission ON submission_pages(submission_id);
CREATE INDEX IF NOT EXISTS idx_marks_evaluation ON evaluation_step_marks(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_annotations_evaluation ON answer_annotations(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_annotations_question ON answer_annotations(question_id);
CREATE INDEX IF NOT EXISTS idx_ai_notes_evaluation ON ai_vision_notes(evaluation_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.executescript(SCHEMA)


def reset_database() -> None:
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    initialize_database()


def create_question_paper(data: dict[str, Any]) -> dict[str, Any]:
    paper_id = new_id("qp")
    created_at = now_iso()
    maximum_marks = sum(float(question["max_marks"]) for question in data["questions"])

    with connection() as conn:
        conn.execute(
            """
            INSERT INTO question_papers (
                id, paper_code, subject_code, subject_name, class_code,
                total_questions, maximum_marks, version, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                data["paper_code"].strip(),
                data["subject_code"].strip(),
                data["subject_name"].strip(),
                data["class_code"].strip(),
                len(data["questions"]),
                maximum_marks,
                data.get("version", 1),
                data.get("status", "active"),
                created_at,
            ),
        )

        for question in data["questions"]:
            question_id = new_id("q")
            conn.execute(
                """
                INSERT INTO questions (
                    id, question_paper_id, question_no, question_text,
                    max_marks, question_type, display_order, reference_solution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    paper_id,
                    question["question_no"],
                    question["question_text"],
                    question["max_marks"],
                    question.get("question_type", "General"),
                    question["display_order"],
                    question.get("reference_solution", ""),
                ),
            )
            for step in question["steps"]:
                conn.execute(
                    """
                    INSERT INTO question_steps (
                        id, question_id, step_no, title, description, max_marks
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("step"),
                        question_id,
                        step["step_no"],
                        step["title"],
                        step.get("description", ""),
                        step["max_marks"],
                    ),
                )
    return get_question_paper(paper_id)


def list_question_papers() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM question_papers ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_question_paper(paper_id_or_code: str) -> dict[str, Any] | None:
    with connection() as conn:
        paper = conn.execute(
            """
            SELECT * FROM question_papers
            WHERE id = ? OR paper_code = ? COLLATE NOCASE
            """,
            (paper_id_or_code, paper_id_or_code),
        ).fetchone()
        if not paper:
            return None
        questions = conn.execute(
            """
            SELECT * FROM questions
            WHERE question_paper_id = ?
            ORDER BY display_order
            """,
            (paper["id"],),
        ).fetchall()
        result = dict(paper)
        result["questions"] = []
        for question in questions:
            item = dict(question)
            item["steps"] = [
                dict(step)
                for step in conn.execute(
                    """
                    SELECT * FROM question_steps
                    WHERE question_id = ?
                    ORDER BY step_no
                    """,
                    (question["id"],),
                ).fetchall()
            ]
            result["questions"].append(item)
    return result


def create_submission(
    *,
    student_id: str,
    student_name: str | None,
    paper_code: str,
    assigned_evaluator_id: str,
    evaluation_batch: str,
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamp = now_iso()
    submission_id = new_id("sub")
    evaluation_id = new_id("ev")

    with connection() as conn:
        paper = conn.execute(
            "SELECT * FROM question_papers WHERE paper_code = ? COLLATE NOCASE",
            (paper_code,),
        ).fetchone()
        if not paper:
            raise LookupError(f"Question paper code '{paper_code}' was not found")

        conn.execute(
            """
            INSERT INTO student_submissions (
                id, student_id, student_name, question_paper_id,
                evaluation_status, assigned_evaluator_id, evaluation_batch,
                submitted_at, updated_at
            ) VALUES (?, ?, ?, ?, 'Not Started', ?, ?, ?, ?)
            """,
            (
                submission_id,
                student_id,
                student_name,
                paper["id"],
                assigned_evaluator_id,
                evaluation_batch,
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO evaluations (
                id, submission_id, evaluator_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'Not Started', ?, ?)
            """,
            (evaluation_id, submission_id, assigned_evaluator_id, timestamp, timestamp),
        )

        page_ids: list[str] = []
        for page_number, page in enumerate(pages, start=1):
            page_id = new_id("page")
            page_ids.append(page_id)
            conn.execute(
                """
                INSERT INTO submission_pages (
                    id, submission_id, page_number, original_filename,
                    stored_path, content_type, width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    submission_id,
                    page_number,
                    page["original_filename"],
                    page["stored_path"],
                    page["content_type"],
                    page.get("width"),
                    page.get("height"),
                ),
            )

        questions = conn.execute(
            """
            SELECT id, display_order FROM questions
            WHERE question_paper_id = ?
            ORDER BY display_order
            """,
            (paper["id"],),
        ).fetchall()
        for question in questions:
            mapped_page = (
                page_ids[min(question["display_order"] - 1, len(page_ids) - 1)]
                if page_ids
                else None
            )
            conn.execute(
                """
                INSERT INTO submission_question_mappings (
                    id, submission_id, question_id, page_id, mapping_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    new_id("map"),
                    submission_id,
                    question["id"],
                    mapped_page,
                    "mapped" if mapped_page else "unmapped",
                ),
            )
    return get_evaluation(evaluation_id)


def list_evaluations() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id AS evaluation_id,
                s.id AS submission_id,
                s.student_id,
                s.student_name,
                p.subject_name AS subject,
                p.subject_code,
                p.paper_code AS question_paper_code,
                p.total_questions,
                e.status,
                e.updated_at,
                p.maximum_marks,
                COALESCE(SUM(m.awarded_marks), 0) AS marks_awarded
            FROM evaluations e
            JOIN student_submissions s ON s.id = e.submission_id
            JOIN question_papers p ON p.id = s.question_paper_id
            LEFT JOIN evaluation_step_marks m ON m.evaluation_id = e.id
            GROUP BY e.id
            ORDER BY e.updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_evaluation(evaluation_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT
                e.id AS evaluation_id,
                e.status,
                e.evaluator_id,
                e.created_at,
                e.updated_at,
                e.completed_at,
                s.id AS submission_id,
                s.student_id,
                s.student_name,
                s.evaluation_batch,
                s.submitted_at,
                p.id AS question_paper_id,
                p.paper_code AS question_paper_code,
                p.subject_code,
                p.subject_name,
                p.class_code,
                p.total_questions,
                p.maximum_marks
            FROM evaluations e
            JOIN student_submissions s ON s.id = e.submission_id
            JOIN question_papers p ON p.id = s.question_paper_id
            WHERE e.id = ?
            """,
            (evaluation_id,),
        ).fetchone()
    return dict(row) if row else None


def get_pages(evaluation_id: str) -> list[dict[str, Any]] | None:
    evaluation = get_evaluation(evaluation_id)
    if not evaluation:
        return None
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id AS page_id, page_number, original_filename, content_type,
                   width, height
            FROM submission_pages
            WHERE submission_id = ?
            ORDER BY page_number
            """,
            (evaluation["submission_id"],),
        ).fetchall()
    return [
        {
            **dict(row),
            "image_url": f"/evaluations/{evaluation_id}/pages/{row['page_id']}/image",
        }
        for row in rows
    ]


def get_page_file(evaluation_id: str, page_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT sp.stored_path, sp.content_type, sp.original_filename
            FROM submission_pages sp
            JOIN evaluations e ON e.submission_id = sp.submission_id
            WHERE e.id = ? AND sp.id = ?
            """,
            (evaluation_id, page_id),
        ).fetchone()
    return dict(row) if row else None


def _question_rows(conn: sqlite3.Connection, evaluation_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            q.id AS question_id,
            q.question_no,
            q.question_text,
            q.max_marks,
            q.question_type,
            q.display_order,
            q.reference_solution,
            sqm.page_id,
            sqm.bbox_json,
            sqm.mapping_status,
            sqm.is_manually_changed,
            sqm.viewed,
            COUNT(qs.id) AS total_steps,
            COUNT(esm.id) AS marked_steps,
            COALESCE(SUM(esm.awarded_marks), 0) AS awarded_marks
        FROM evaluations e
        JOIN student_submissions s ON s.id = e.submission_id
        JOIN questions q ON q.question_paper_id = s.question_paper_id
        LEFT JOIN question_steps qs ON qs.question_id = q.id
        LEFT JOIN evaluation_step_marks esm
            ON esm.evaluation_id = e.id AND esm.step_id = qs.id
        LEFT JOIN submission_question_mappings sqm
            ON sqm.submission_id = s.id AND sqm.question_id = q.id
        WHERE e.id = ?
        GROUP BY q.id
        ORDER BY q.display_order
        """,
        (evaluation_id,),
    ).fetchall()


def _question_status(marked_steps: int, total_steps: int) -> str:
    if marked_steps == 0:
        return "Not Started"
    return "Completed" if marked_steps == total_steps else "In Progress"


def list_questions(evaluation_id: str) -> list[dict[str, Any]] | None:
    if not get_evaluation(evaluation_id):
        return None
    with connection() as conn:
        rows = _question_rows(conn, evaluation_id)
    return [
        {
            **{key: row[key] for key in row.keys() if key != "bbox_json"},
            "bbox": json.loads(row["bbox_json"]) if row["bbox_json"] else None,
            "is_manually_changed": bool(row["is_manually_changed"]),
            "viewed": bool(row["viewed"]),
            "status": _question_status(row["marked_steps"], row["total_steps"]),
        }
        for row in rows
    ]


def get_question(evaluation_id: str, question_id: str) -> dict[str, Any] | None:
    questions = list_questions(evaluation_id)
    if questions is None:
        return None
    question = next((item for item in questions if item["question_id"] == question_id), None)
    if not question:
        return None
    with connection() as conn:
        steps = conn.execute(
            """
            SELECT
                qs.id AS step_id,
                qs.step_no,
                qs.title,
                qs.description,
                qs.max_marks,
                esm.awarded_marks,
                esm.updated_at
            FROM question_steps qs
            LEFT JOIN evaluation_step_marks esm
                ON esm.step_id = qs.id AND esm.evaluation_id = ?
            WHERE qs.question_id = ?
            ORDER BY qs.step_no
            """,
            (evaluation_id, question_id),
        ).fetchall()
    question["steps"] = [
        {
            **dict(step),
            "status": "Completed" if step["awarded_marks"] is not None else "Pending",
        }
        for step in steps
    ]
    return question


def _touch_evaluation(conn: sqlite3.Connection, evaluation_id: str) -> None:
    timestamp = now_iso()
    conn.execute(
        "UPDATE evaluations SET status = 'In Progress', updated_at = ? WHERE id = ?",
        (timestamp, evaluation_id),
    )
    conn.execute(
        """
        UPDATE student_submissions
        SET evaluation_status = 'In Progress', updated_at = ?
        WHERE id = (SELECT submission_id FROM evaluations WHERE id = ?)
        """,
        (timestamp, evaluation_id),
    )


def save_step_mark(
    evaluation_id: str, step_id: str, awarded_marks: float
) -> dict[str, Any]:
    with connection() as conn:
        step = conn.execute(
            """
            SELECT qs.*, q.id AS question_id
            FROM question_steps qs
            JOIN questions q ON q.id = qs.question_id
            JOIN student_submissions s ON s.question_paper_id = q.question_paper_id
            JOIN evaluations e ON e.submission_id = s.id
            WHERE e.id = ? AND qs.id = ?
            """,
            (evaluation_id, step_id),
        ).fetchone()
        if not step:
            raise LookupError("Evaluation step was not found")
        if awarded_marks > step["max_marks"]:
            raise ValueError(
                f"Marks cannot exceed the step maximum of {step['max_marks']:g}"
            )
        timestamp = now_iso()
        conn.execute(
            """
            INSERT INTO evaluation_step_marks (
                id, evaluation_id, step_id, awarded_marks, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(evaluation_id, step_id)
            DO UPDATE SET awarded_marks = excluded.awarded_marks,
                          updated_at = excluded.updated_at
            """,
            (new_id("mark"), evaluation_id, step_id, awarded_marks, timestamp),
        )
        _touch_evaluation(conn, evaluation_id)
        question_id = step["question_id"]
    return get_question(evaluation_id, question_id)


def assign_full_marks(evaluation_id: str, question_id: str) -> dict[str, Any]:
    with connection() as conn:
        steps = conn.execute(
            """
            SELECT qs.id, qs.step_no, qs.max_marks, q.question_no
            FROM question_steps qs
            JOIN questions q ON q.id = qs.question_id
            JOIN student_submissions s ON s.question_paper_id = q.question_paper_id
            JOIN evaluations e ON e.submission_id = s.id
            WHERE e.id = ? AND q.id = ?
            """,
            (evaluation_id, question_id),
        ).fetchall()
        if not steps:
            raise LookupError("Question was not found")
        timestamp = now_iso()
        for step in steps:
            conn.execute(
                """
                INSERT INTO evaluation_step_marks (
                    id, evaluation_id, step_id, awarded_marks, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id, step_id)
                DO UPDATE SET awarded_marks = excluded.awarded_marks,
                              updated_at = excluded.updated_at
                """,
                (
                    new_id("mark"),
                    evaluation_id,
                    step["id"],
                    step["max_marks"],
                    timestamp,
                ),
            )
            conn.execute(
                """
                UPDATE answer_annotations
                SET text = ?, updated_at = ?
                WHERE evaluation_id = ? AND step_id = ?
                """,
                (
                    f"{step['question_no']} · S{step['step_no']} · "
                    f"{step['max_marks']:g}/{step['max_marks']:g}",
                    timestamp,
                    evaluation_id,
                    step["id"],
                ),
            )
        conn.execute(
            """
            DELETE FROM answer_annotations
            WHERE evaluation_id = ? AND question_id = ? AND step_id IS NULL
            """,
            (evaluation_id, question_id),
        )
        _touch_evaluation(conn, evaluation_id)
    return get_question(evaluation_id, question_id)


def reset_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
    with connection() as conn:
        question = conn.execute(
            """
            SELECT q.id
            FROM questions q
            JOIN student_submissions s ON s.question_paper_id = q.question_paper_id
            JOIN evaluations e ON e.submission_id = s.id
            WHERE e.id = ? AND q.id = ?
            """,
            (evaluation_id, question_id),
        ).fetchone()
        if not question:
            raise LookupError("Question was not found")
        conn.execute(
            """
            DELETE FROM evaluation_step_marks
            WHERE evaluation_id = ?
              AND step_id IN (
                  SELECT id FROM question_steps WHERE question_id = ?
              )
            """,
            (evaluation_id, question_id),
        )
        conn.execute(
            """
            DELETE FROM answer_annotations
            WHERE evaluation_id = ? AND question_id = ?
            """,
            (evaluation_id, question_id),
        )
        _touch_evaluation(conn, evaluation_id)
    return get_question(evaluation_id, question_id)


def reset_evaluation_marks(evaluation_id: str) -> dict[str, Any]:
    if not get_evaluation(evaluation_id):
        raise LookupError("Evaluation was not found")
    timestamp = now_iso()
    with connection() as conn:
        conn.execute(
            "DELETE FROM evaluation_step_marks WHERE evaluation_id = ?",
            (evaluation_id,),
        )
        conn.execute(
            "DELETE FROM answer_annotations WHERE evaluation_id = ?",
            (evaluation_id,),
        )
        conn.execute(
            """
            UPDATE evaluations
            SET status = 'Not Started', updated_at = ?, completed_at = NULL
            WHERE id = ?
            """,
            (timestamp, evaluation_id),
        )
        conn.execute(
            """
            UPDATE student_submissions
            SET evaluation_status = 'Not Started', updated_at = ?
            WHERE id = (SELECT submission_id FROM evaluations WHERE id = ?)
            """,
            (timestamp, evaluation_id),
        )
    progress = get_progress(evaluation_id)
    if progress is None:
        raise LookupError("Evaluation was not found")
    return progress


def list_annotations(evaluation_id: str) -> list[dict[str, Any]] | None:
    if not get_evaluation(evaluation_id):
        return None
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id AS annotation_id, question_id, step_id, page_id, text,
                   x, y, width, height, created_at, updated_at
            FROM answer_annotations
            WHERE evaluation_id = ?
            ORDER BY created_at
            """,
            (evaluation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_annotation(
    evaluation_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    with connection() as conn:
        valid = conn.execute(
            """
            SELECT q.id
            FROM evaluations e
            JOIN student_submissions s ON s.id = e.submission_id
            JOIN questions q
              ON q.question_paper_id = s.question_paper_id
             AND q.id = ?
            JOIN submission_pages sp
              ON sp.submission_id = s.id
             AND sp.id = ?
            LEFT JOIN question_steps qs
              ON qs.question_id = q.id
             AND qs.id = ?
            WHERE e.id = ?
              AND (? IS NULL OR qs.id IS NOT NULL)
            """,
            (
                data["question_id"],
                data["page_id"],
                data.get("step_id"),
                evaluation_id,
                data.get("step_id"),
            ),
        ).fetchone()
        if not valid:
            raise LookupError("Question, step, or page was not found")
        if data.get("step_id") is None:
            conn.execute(
                """
                DELETE FROM answer_annotations
                WHERE evaluation_id = ? AND question_id = ? AND step_id IS NULL
                """,
                (evaluation_id, data["question_id"]),
            )
        annotation_id = new_id("ann")
        timestamp = now_iso()
        conn.execute(
            """
            INSERT INTO answer_annotations (
                id, evaluation_id, question_id, step_id, page_id, text,
                x, y, width, height, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation_id,
                evaluation_id,
                data["question_id"],
                data.get("step_id"),
                data["page_id"],
                data["text"],
                data["x"],
                data["y"],
                data["width"],
                data["height"],
                timestamp,
                timestamp,
            ),
        )
    return next(
        item
        for item in list_annotations(evaluation_id) or []
        if item["annotation_id"] == annotation_id
    )


def accept_ai_vision_marks(
    evaluation_id: str,
    *,
    question_id: str,
    page_id: str,
    marks: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    reasoning: str = "",
) -> dict[str, Any]:
    with connection() as conn:
        question = conn.execute(
            """
            SELECT q.id, q.question_no, q.max_marks
            FROM evaluations e
            JOIN student_submissions s ON s.id = e.submission_id
            JOIN questions q
              ON q.question_paper_id = s.question_paper_id
             AND q.id = ?
            JOIN submission_pages sp
              ON sp.submission_id = s.id
             AND sp.id = ?
            WHERE e.id = ?
            """,
            (question_id, page_id, evaluation_id),
        ).fetchone()
        if not question:
            raise LookupError("Question or answer-sheet page was not found")

        steps = conn.execute(
            """
            SELECT id, step_no, max_marks
            FROM question_steps
            WHERE question_id = ?
            ORDER BY step_no
            """,
            (question_id,),
        ).fetchall()
        if len(marks) != len(steps):
            raise ValueError("AI marks must contain one value for every step")
        for mark, step in zip(marks, steps):
            if mark < 0 or mark > step["max_marks"]:
                raise ValueError(
                    f"Marks for step {step['step_no']} must be between 0 and "
                    f"{step['max_marks']:g}"
                )

        timestamp = now_iso()
        for mark, step in zip(marks, steps):
            conn.execute(
                """
                INSERT INTO evaluation_step_marks (
                    id, evaluation_id, step_id, awarded_marks, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id, step_id)
                DO UPDATE SET awarded_marks = excluded.awarded_marks,
                              updated_at = excluded.updated_at
                """,
                (new_id("mark"), evaluation_id, step["id"], mark, timestamp),
            )

        conn.execute(
            """
            DELETE FROM answer_annotations
            WHERE evaluation_id = ? AND question_id = ?
            """,
            (evaluation_id, question_id),
        )
        step_text = ",".join(
            f"{mark:g}/{step['max_marks']:g}"
            for mark, step in zip(marks, steps)
        )
        awarded_total = sum(marks)
        annotation_id = new_id("ann")
        conn.execute(
            """
            INSERT INTO answer_annotations (
                id, evaluation_id, question_id, step_id, page_id, text,
                x, y, width, height, created_at, updated_at
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation_id,
                evaluation_id,
                question_id,
                page_id,
                f"TAI|{question['question_no']}|{step_text}|"
                f"{awarded_total:g}/{question['max_marks']:g}",
                min(0.82, x + width + 0.01),
                min(0.88, y + height + 0.01),
                0.18,
                0.12,
                timestamp,
                timestamp,
            ),
        )
        # Hidden for now: retain model rationale so a future review UI can show
        # why the AI awarded each mark without reviving the old dummy note flow.
        if reasoning:
            conn.execute(
                """
                INSERT INTO ai_vision_notes (
                    id, evaluation_id, question_id, page_id, analysis,
                    x, y, width, height, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("ai"),
                    evaluation_id,
                    question_id,
                    page_id,
                    reasoning,
                    x,
                    y,
                    width,
                    height,
                    timestamp,
                ),
            )
        _touch_evaluation(conn, evaluation_id)

    annotation = next(
        item
        for item in list_annotations(evaluation_id) or []
        if item["annotation_id"] == annotation_id
    )
    return {
        "question": get_question(evaluation_id, question_id),
        "annotation": annotation,
    }


def update_annotation(
    evaluation_id: str, annotation_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    updates = {key: value for key, value in data.items() if value is not None}
    with connection() as conn:
        existing = conn.execute(
            """
            SELECT id FROM answer_annotations
            WHERE id = ? AND evaluation_id = ?
            """,
            (annotation_id, evaluation_id),
        ).fetchone()
        if not existing:
            raise LookupError("Annotation was not found")
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"""
                UPDATE answer_annotations
                SET {assignments}, updated_at = ?
                WHERE id = ? AND evaluation_id = ?
                """,
                (*updates.values(), now_iso(), annotation_id, evaluation_id),
            )
    return next(
        item
        for item in list_annotations(evaluation_id) or []
        if item["annotation_id"] == annotation_id
    )


def list_ai_vision_notes(evaluation_id: str) -> list[dict[str, Any]] | None:
    if not get_evaluation(evaluation_id):
        return None
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id AS note_id, question_id, page_id, analysis,
                   x, y, width, height, created_at
            FROM ai_vision_notes
            WHERE evaluation_id = ?
            ORDER BY created_at
            """,
            (evaluation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def focus_question(evaluation_id: str, question_id: str) -> dict[str, Any]:
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE submission_question_mappings
            SET viewed = 1
            WHERE submission_id = (
                SELECT submission_id FROM evaluations WHERE id = ?
            ) AND question_id = ?
            """,
            (evaluation_id, question_id),
        )
        if cursor.rowcount == 0:
            raise LookupError("Question mapping was not found")
        _touch_evaluation(conn, evaluation_id)
    return get_question(evaluation_id, question_id)


def adjacent_question(
    evaluation_id: str, question_id: str, direction: int
) -> dict[str, Any] | None:
    questions = list_questions(evaluation_id)
    if not questions:
        return None
    index = next(
        (position for position, item in enumerate(questions) if item["question_id"] == question_id),
        None,
    )
    if index is None:
        return None
    target = questions[(index + direction) % len(questions)]
    return focus_question(evaluation_id, target["question_id"])


def change_mapping(
    evaluation_id: str,
    question_id: str,
    to_question_id: str,
    page_id: str | None,
    bbox: dict[str, float] | None,
) -> dict[str, Any]:
    with connection() as conn:
        submission = conn.execute(
            "SELECT submission_id FROM evaluations WHERE id = ?",
            (evaluation_id,),
        ).fetchone()
        if not submission:
            raise LookupError("Evaluation was not found")
        source = conn.execute(
            """
            SELECT * FROM submission_question_mappings
            WHERE submission_id = ? AND question_id = ?
            """,
            (submission["submission_id"], question_id),
        ).fetchone()
        target = conn.execute(
            """
            SELECT * FROM submission_question_mappings
            WHERE submission_id = ? AND question_id = ?
            """,
            (submission["submission_id"], to_question_id),
        ).fetchone()
        if not source or not target:
            raise LookupError("Source or target question mapping was not found")

        new_page_id = page_id or source["page_id"]
        new_bbox = json.dumps(bbox) if bbox is not None else source["bbox_json"]
        conn.execute(
            """
            UPDATE submission_question_mappings
            SET page_id = ?, bbox_json = ?, is_manually_changed = 1
            WHERE id = ?
            """,
            (target["page_id"], target["bbox_json"], source["id"]),
        )
        conn.execute(
            """
            UPDATE submission_question_mappings
            SET page_id = ?, bbox_json = ?, is_manually_changed = 1
            WHERE id = ?
            """,
            (new_page_id, new_bbox, target["id"]),
        )
        _touch_evaluation(conn, evaluation_id)
    return get_question(evaluation_id, to_question_id)


def get_progress(evaluation_id: str) -> dict[str, Any] | None:
    evaluation = get_evaluation(evaluation_id)
    questions = list_questions(evaluation_id)
    if not evaluation or questions is None:
        return None
    total_questions = len(questions)
    evaluated = sum(question["status"] == "Completed" for question in questions)
    viewed = sum(question["viewed"] for question in questions)
    total_marks = sum(float(question["awarded_marks"]) for question in questions)
    completion = round((evaluated / total_questions) * 100, 1) if total_questions else 0
    return {
        "questions_viewed": viewed,
        "total_questions": total_questions,
        "questions_evaluated": evaluated,
        "total_marks": total_marks,
        "maximum_marks": evaluation["maximum_marks"],
        "completion_percentage": completion,
        "status": evaluation["status"],
    }


def get_marks_summary(evaluation_id: str) -> dict[str, Any] | None:
    evaluation = get_evaluation(evaluation_id)
    questions = list_questions(evaluation_id)
    if not evaluation or questions is None:
        return None
    return {
        "evaluation_id": evaluation_id,
        "question_marks": [
            {
                "question_id": question["question_id"],
                "question_no": question["question_no"],
                "awarded": question["awarded_marks"],
                "max": question["max_marks"],
                "status": question["status"],
            }
            for question in questions
        ],
        "total_awarded": sum(float(question["awarded_marks"]) for question in questions),
        "maximum_marks": evaluation["maximum_marks"],
    }


def submit_evaluation(evaluation_id: str) -> dict[str, Any]:
    questions = list_questions(evaluation_id)
    if questions is None:
        raise LookupError("Evaluation was not found")
    missing = [
        question["question_no"]
        for question in questions
        if question["status"] != "Completed"
    ]
    if missing:
        raise ValueError(f"All questions must be marked before submission: {', '.join(missing)}")
    timestamp = now_iso()
    with connection() as conn:
        conn.execute(
            """
            UPDATE evaluations
            SET status = 'Completed', updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, evaluation_id),
        )
        conn.execute(
            """
            UPDATE student_submissions
            SET evaluation_status = 'Completed', updated_at = ?
            WHERE id = (SELECT submission_id FROM evaluations WHERE id = ?)
            """,
            (timestamp, evaluation_id),
        )
    return get_evaluation(evaluation_id)


def count_question_papers() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM question_papers").fetchone()[0])
