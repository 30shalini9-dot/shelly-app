from __future__ import annotations

import math
import unittest

from app.ai_vision import build_evaluation_prompt, normalize_step_marks


class AiVisionTestCase(unittest.TestCase):
    def test_normalizes_marks_to_configured_steps(self) -> None:
        self.assertEqual(
            normalize_step_marks(
                {"marks": [1.5, -1, math.inf, 0.75]},
                [1, 2, 3],
            ),
            [1, 0, 0],
        )
        self.assertEqual(
            normalize_step_marks({"marks": [0.5]}, [1, 2, 3]),
            [0.5, 0, 0],
        )
        self.assertEqual(
            normalize_step_marks({"marks": [0.5, "invalid", 2]}, [1, 1, 3]),
            [0.5, 0, 2],
        )
        self.assertEqual(
            normalize_step_marks("not valid model output", [1, 2]),
            [0, 0],
        )

    def test_builds_prompt_from_question_reference_and_steps(self) -> None:
        prompt = build_evaluation_prompt(
            question_text="What is photosynthesis?",
            reference_solution="Plants prepare food using sunlight.",
            steps=[
                {
                    "step_no": 1,
                    "title": "Definition",
                    "description": "Defines photosynthesis",
                    "max_marks": 1,
                },
                {
                    "step_no": 2,
                    "title": "Process",
                    "description": "",
                    "max_marks": 2,
                },
            ],
        )

        self.assertIn("Question:\nWhat is photosynthesis?", prompt)
        self.assertIn(
            "Reference Solution:\nPlants prepare food using sunlight.",
            prompt,
        )
        self.assertIn(
            "1. Definition: Defines photosynthesis (max 1)",
            prompt,
        )
        self.assertIn("2. Process (max 2)", prompt)
        self.assertTrue(prompt.endswith("Evaluate the attached answer image."))


if __name__ == "__main__":
    unittest.main()
