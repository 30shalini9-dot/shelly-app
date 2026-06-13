from __future__ import annotations

import argparse
from pathlib import Path

from . import database


SAMPLE_PAPER = {
    "paper_code": "SCI-10-A",
    "subject_code": "SCI",
    "subject_name": "Science",
    "class_code": "10",
    "version": 1,
    "status": "active",
    "questions": [
        {
            "question_no": "Q1",
            "question_text": "Define photosynthesis and write its word equation.",
            "max_marks": 2,
            "question_type": "Short Answer",
            "display_order": 1,
            "reference_solution": (
                "Photosynthesis uses sunlight to convert carbon dioxide and water "
                "into glucose and oxygen."
            ),
            "steps": [
                {
                    "step_no": 1,
                    "title": "Definition",
                    "description": "States the purpose of photosynthesis.",
                    "max_marks": 1,
                },
                {
                    "step_no": 2,
                    "title": "Word equation",
                    "description": "Carbon dioxide + water -> glucose + oxygen.",
                    "max_marks": 1,
                },
            ],
        },
        {
            "question_no": "Q2",
            "question_text": "Explain the role of chlorophyll in photosynthesis.",
            "max_marks": 3,
            "question_type": "Short Answer",
            "display_order": 2,
            "reference_solution": (
                "Chlorophyll absorbs light energy, which drives the reactions used "
                "to prepare glucose."
            ),
            "steps": [
                {
                    "step_no": 1,
                    "title": "Location",
                    "description": "Identifies chlorophyll in chloroplasts.",
                    "max_marks": 1,
                },
                {
                    "step_no": 2,
                    "title": "Light absorption",
                    "description": "Explains absorption of light energy.",
                    "max_marks": 1,
                },
                {
                    "step_no": 3,
                    "title": "Use of energy",
                    "description": "Connects captured energy to glucose production.",
                    "max_marks": 1,
                },
            ],
        },
        {
            "question_no": "Q3",
            "question_text": "Describe an experiment that shows light is needed for photosynthesis.",
            "max_marks": 5,
            "question_type": "Long Answer",
            "display_order": 3,
            "reference_solution": (
                "Destarch a plant, cover part of a leaf, expose it to light, then "
                "perform the iodine test. Only the exposed section turns blue-black."
            ),
            "steps": [
                {
                    "step_no": 1,
                    "title": "Destarch plant",
                    "description": "Keeps the plant in darkness before the experiment.",
                    "max_marks": 1,
                },
                {
                    "step_no": 2,
                    "title": "Cover leaf",
                    "description": "Covers part of a leaf with opaque paper.",
                    "max_marks": 1,
                },
                {
                    "step_no": 3,
                    "title": "Expose and test",
                    "description": "Exposes to light and carries out the iodine test.",
                    "max_marks": 2,
                },
                {
                    "step_no": 4,
                    "title": "Conclusion",
                    "description": "Concludes that light is required to form starch.",
                    "max_marks": 1,
                },
            ],
        },
    ],
}


def _write_demo_page(path: Path, page_number: int, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text_rows = "\n".join(
        (
            f'<text x="120" y="{330 + index * 64}" font-family="Georgia, serif" '
            f'font-size="30" fill="#233047">{line}</text>'
        )
        for index, line in enumerate(lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="1754" viewBox="0 0 1240 1754">
  <rect width="1240" height="1754" fill="#f9f5e9"/>
  <rect x="72" y="58" width="1096" height="1638" rx="10" fill="#fffdf7" stroke="#d8d1c0" stroke-width="3"/>
  <text x="120" y="140" font-family="Arial, sans-serif" font-size="24" fill="#5b6472">SHELDON SAMPLE ANSWER SHEET</text>
  <text x="120" y="205" font-family="Arial, sans-serif" font-size="20" fill="#5b6472">Student: STU001    Paper: SCI-10-A    Page: {page_number}</text>
  <line x1="120" y1="245" x2="1120" y2="245" stroke="#c7d5e5" stroke-width="2"/>
  {text_rows}
  <g stroke="#dce6f0" stroke-width="2">
    <line x1="120" y1="1100" x2="1120" y2="1100"/>
    <line x1="120" y1="1170" x2="1120" y2="1170"/>
    <line x1="120" y1="1240" x2="1120" y2="1240"/>
    <line x1="120" y1="1310" x2="1120" y2="1310"/>
    <line x1="120" y1="1380" x2="1120" y2="1380"/>
  </g>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def seed_database() -> None:
    database.initialize_database()
    if database.count_question_papers() > 0:
        return

    database.create_question_paper(SAMPLE_PAPER)
    demo_dir = database.UPLOAD_DIR / "demo-submission"
    page_one = demo_dir / "page-1.svg"
    page_two = demo_dir / "page-2.svg"
    _write_demo_page(
        page_one,
        1,
        [
            "Q1. Photosynthesis is how green plants make food using sunlight.",
            "Carbon dioxide + water -> glucose + oxygen.",
            "",
            "Q2. Chlorophyll is found in chloroplasts.",
            "It traps light energy so the plant can make glucose.",
        ],
    )
    _write_demo_page(
        page_two,
        2,
        [
            "Q3. First keep the plant in darkness to remove stored starch.",
            "Cover part of one leaf and place the plant in sunlight.",
            "After several hours, test the leaf with iodine.",
            "The exposed area turns blue-black, showing that light is needed.",
        ],
    )
    database.create_submission(
        student_id="STU001",
        student_name="Rahul Sharma",
        paper_code="SCI-10-A",
        assigned_evaluator_id="eval_001",
        evaluation_batch="June 2026",
        pages=[
            {
                "original_filename": "page-1.svg",
                "stored_path": str(page_one),
                "content_type": "image/svg+xml",
                "width": 1240,
                "height": 1754,
            },
            {
                "original_filename": "page-2.svg",
                "stored_path": str(page_two),
                "content_type": "image/svg+xml",
                "width": 1240,
                "height": 1754,
            },
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Sheldon local database")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the local database before loading sample data",
    )
    args = parser.parse_args()
    if args.reset:
        database.reset_database()
    seed_database()
    print(f"Database ready at {database.DATABASE_PATH}")


if __name__ == "__main__":
    main()
