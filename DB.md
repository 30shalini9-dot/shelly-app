Use 3 main entities:

1. question_paper
2. question_paper_questions
3. student_submission

1. Question Paper Storage

This stores the master paper and marking structure.

{
  "question_paper_id": "qp_001",
  "paper_code": "SCI-10-A",
  "subject_code": "SCI",
  "subject_name": "Science",
  "class_code": "10",
  "total_questions": 20,
  "maximum_marks": 50,
  "version": 1,
  "status": "active",
  "created_at": "2026-06-13T10:00:00"
}

2. Question + Step Storage

Each question has steps and marks.

{
  "question_id": "q_004",
  "question_paper_id": "qp_001",
  "question_no": "Q4",
  "question_text": "Explain the process of photosynthesis.",
  "max_marks": 5,
  "question_type": "Long Answer",
  "display_order": 4,
  "steps": [
    {
      "step_id": "s_001",
      "step_no": 1,
      "title": "Definition",
      "description": "Correct definition of photosynthesis",
      "max_marks": 1
    },
    {
      "step_id": "s_002",
      "step_no": 2,
      "title": "Diagram",
      "description": "Correct labeled diagram",
      "max_marks": 2
    },
    {
      "step_id": "s_003",
      "step_no": 3,
      "title": "Explanation",
      "description": "Explains sunlight, chlorophyll, carbon dioxide and water",
      "max_marks": 2
    }
  ],
  "reference_solution": "Photosynthesis is the process by which green plants prepare food using sunlight, carbon dioxide and water."
}

3. New Student Submission Storage

This stores one student’s uploaded answer sheet.

{
  "submission_id": "sub_001",
  "student_id": "STU001",
  "student_name": "Rahul Sharma",
  "question_paper_id": "qp_001",
  "evaluation_status": "not_started",
  "assigned_evaluator_id": "eval_001",
  "total_awarded_marks": 0,
  "maximum_marks": 50,
  "submitted_at": "2026-06-13T10:30:00",
  "pages": [
    {
      "page_id": "page_001",
      "page_number": 1,
      "image_url": "s3://sheldon/sub_001/page_001.png",
      "width": 2480,
      "height": 3508
    },
    {
      "page_id": "page_002",
      "page_number": 2,
      "image_url": "s3://sheldon/sub_001/page_002.png",
      "width": 2480,
      "height": 3508
    }
  ]
}

4. Question Mapping for Student Submission

This tells which answer segment belongs to which question.

{
  "mapping_id": "map_001",
  "submission_id": "sub_001",
  "question_id": "q_004",
  "question_no": "Q4",
  "page_id": "page_002",
  "bbox": {
    "x": 120,
    "y": 450,
    "w": 2100,
    "h": 900
  },
  "mapping_status": "mapped",
  "is_manually_changed": false
}

5. Marks Storage

Store marks separately from the question paper.

{
  "evaluation_id": "ev_001",
  "submission_id": "sub_001",
  "question_id": "q_004",
  "step_marks": [
    {
      "step_id": "s_001",
      "awarded_marks": 1,
      "max_marks": 1,
      "status": "completed"
    },
    {
      "step_id": "s_002",
      "awarded_marks": 2,
      "max_marks": 2,
      "status": "completed"
    },
    {
      "step_id": "s_003",
      "awarded_marks": 1.5,
      "max_marks": 2,
      "status": "completed"
    }
  ],
  "question_total": 4.5,
  "question_max": 5,
  "status": "completed"
}

Recommended DB Tables

question_papers
questions
question_steps
student_submissions
submission_pages
submission_question_mappings
evaluations
evaluation_step_marks

Simple Flow

Step	Action	Store In
1	Create question paper	question_papers
2	Add questions	questions
3	Add marking steps	question_steps
4	Upload student answer sheet	student_submissions
5	Store page images	submission_pages
6	Map answer area to question	submission_question_mappings
7	Evaluator gives marks	evaluation_step_marks
8	Calculate final score	evaluations