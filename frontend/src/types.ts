export type EvaluationStatus = "Not Started" | "In Progress" | "Completed";

export interface EvaluationListItem {
  evaluation_id: string;
  submission_id: string;
  student_id: string;
  student_name?: string;
  subject: string;
  subject_code: string;
  question_paper_code: string;
  total_questions: number;
  status: EvaluationStatus;
  updated_at: string;
  maximum_marks: number;
  marks_awarded: number;
}

export interface Evaluation {
  evaluation_id: string;
  submission_id: string;
  student_id: string;
  student_name?: string;
  evaluation_batch: string;
  status: EvaluationStatus;
  question_paper_code: string;
  subject_code: string;
  subject_name: string;
  class_code: string;
  total_questions: number;
  maximum_marks: number;
}

export interface Page {
  page_id: string;
  page_number: number;
  original_filename: string;
  content_type: string;
  image_url: string;
}

export interface Step {
  step_id: string;
  step_no: number;
  title: string;
  description: string;
  max_marks: number;
  awarded_marks: number | null;
  status: "Pending" | "Completed";
}

export interface Question {
  question_id: string;
  question_no: string;
  question_text: string;
  max_marks: number;
  question_type: string;
  display_order: number;
  reference_solution: string;
  page_id: string | null;
  awarded_marks: number;
  total_steps: number;
  marked_steps: number;
  viewed: boolean;
  status: EvaluationStatus;
  steps?: Step[];
}

export interface Progress {
  questions_viewed: number;
  total_questions: number;
  questions_evaluated: number;
  total_marks: number;
  maximum_marks: number;
  completion_percentage: number;
  status: EvaluationStatus;
}

export interface QuestionPaper {
  id: string;
  paper_code: string;
  subject_code: string;
  subject_name: string;
  class_code: string;
  total_questions: number;
  maximum_marks: number;
  status: string;
}

export interface Annotation {
  annotation_id: string;
  question_id: string;
  step_id: string | null;
  page_id: string;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AiVisionNote {
  note_id: string;
  question_id: string;
  page_id: string;
  analysis: string;
  x: number;
  y: number;
  width: number;
  height: number;
  created_at: string;
}
