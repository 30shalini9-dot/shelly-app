#!/usr/bin/env python3

"""
Step-wise answer evaluation using Qwen 3.5 via Ollama.

Inputs:
- Question text
- Step-wise marking criteria
- Answer image

Output:
{
    "marks": [1.0, 0.5, 0.0]
}

No total is calculated.
"""

import argparse
import ast
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

MODEL = "qwen3.5:4b"


SYSTEM_PROMPT = """
You are a strict answer evaluator.

You will receive:

1. A question.
2. Step-wise marking criteria.
3. A student's answer image.

Evaluate each step independently.

Rules:

- Award marks only according to the supplied steps.
- Respect maximum marks for every step.
- Partial marks are allowed.
- Do not calculate totals.
- Do not explain.
- Do not justify marks.
- Do not return markdown.

You MUST call submit_marks exactly once.

Example:

submit_marks([1,0.5,0])

Return only marks for each step in order.
""".strip()


def submit_marks(marks: list[float]) -> dict:
    """
    Tool used by the model.

    Example:
    submit_marks([1,0.5,0])
    """
    return {"marks": marks}


def normalize_marks(value: Any) -> list[float]:
    """
    Accepts:
    [1,0.5,0]
    {"marks":[1,0.5,0]}
    "1,0.5,0"
    "[1,0.5,0]"
    """

    if isinstance(value, list):
        marks = []
        for item in value:
            try:
                marks.append(float(item))
            except (TypeError, ValueError):
                marks.append(0.0)
        return marks

    if isinstance(value, dict):
        if "marks" in value:
            return normalize_marks(value["marks"])

    text = str(value).strip()

    try:
        obj = json.loads(text)

        if isinstance(obj, dict) and "marks" in obj:
            return normalize_marks(obj["marks"])

        if isinstance(obj, list):
            return normalize_marks(obj)

    except Exception:
        pass

    try:
        obj = ast.literal_eval(text)

        if isinstance(obj, dict) and "marks" in obj:
            return normalize_marks(obj["marks"])

        if isinstance(obj, list):
            return normalize_marks(obj)

    except Exception:
        pass

    nums = re.findall(r"-?\d+(?:\.\d+)?", text)

    if nums:
        return [float(x) for x in nums]

    raise ValueError(f"Unable to parse marks: {text}")


def normalize_step_marks(value: Any, maximum_marks: list[float]) -> list[float]:
    """Return exactly one safe mark for every configured question step."""
    try:
        parsed_marks = normalize_marks(value)
    except (TypeError, ValueError):
        parsed_marks = []

    normalized: list[float] = []
    for index, maximum in enumerate(maximum_marks):
        mark = parsed_marks[index] if index < len(parsed_marks) else 0.0
        if not math.isfinite(mark):
            mark = 0.0
        normalized.append(min(float(maximum), max(0.0, mark)))
    return normalized


def build_evaluation_prompt(
    *,
    question_text: str,
    reference_solution: str,
    steps: list[dict[str, Any]],
) -> str:
    step_lines = []
    for step in steps:
        criterion = ": ".join(
            part.strip()
            for part in (str(step["title"]), str(step.get("description", "")))
            if part.strip()
        )
        step_lines.append(
            f"{step['step_no']}. {criterion} (max {step['max_marks']:g})"
        )

    return "\n\n".join(
        (
            f"Question:\n{question_text.strip()}",
            "Reference Solution:\n"
            + (reference_solution.strip() or "No reference solution provided."),
            "Steps:\n" + "\n".join(step_lines),
            "Evaluate the attached answer image.",
        )
    )


def evaluate_answer(
    question: str,
    image_path: str,
    model: str = MODEL,
) -> dict:
    try:
        from ollama import chat
    except ImportError as exc:
        raise RuntimeError(
            "The ollama Python package is required for AI Vision evaluation"
        ) from exc

    image_file = Path(image_path).expanduser()

    if not image_file.exists():
        raise FileNotFoundError(image_path)

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": question,
            "images": [str(image_file.resolve())],
        },
    ]

    # Keep this call aligned with the standalone evaluator. In particular, use
    # the module-level chat helper and a durable image path supplied by the API.
    response = chat(
        model=model,
        messages=messages,
        tools=[submit_marks],
        think=False,
        options={
            "temperature": 0,
        },
    )

    tool_calls = response.message.tool_calls or []
    response_data = (
        response.model_dump(mode="json")
        if hasattr(response, "model_dump")
        else str(response)
    )
    hidden_reasoning = (response.message.content or "").strip()

    # Preferred path: tool call
    if tool_calls:

        call = tool_calls[0]

        if call.function.name == "submit_marks":

            args = call.function.arguments

            marks = normalize_marks(
                args.get("marks", [])
            )

            return {
                "marks": marks,
                "reasoning": hidden_reasoning,
                "raw_response": response_data,
            }

    # Fallback path: parse text response
    marks = normalize_marks(
        response.message.content
    )

    return {
        "marks": marks,
        "reasoning": hidden_reasoning,
        "raw_response": response_data,
    }


def parse_args():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--image",
        required=True,
        help="Answer image path",
    )

    parser.add_argument(
        "--model",
        default=MODEL,
    )

    parser.add_argument(
        "question",
        nargs="*",
        help="Question and marking criteria",
    )

    return parser.parse_args()


def main():

    args = parse_args()

    if args.question:
        question = " ".join(args.question)

    elif not sys.stdin.isatty():
        question = sys.stdin.read()

    else:
        raise ValueError("Question required")

    result = evaluate_answer(
        question=question,
        image_path=args.image,
        model=args.model,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
