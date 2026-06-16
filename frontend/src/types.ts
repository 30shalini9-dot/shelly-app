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
  agent_mode: boolean;
  agent_status: AgentJobStatus | null;
  agent_processed_questions: number | null;
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
  agent_mode: boolean;
  agent_status: AgentJobStatus | null;
}

export interface Page {
  page_id: string;
  page_number: number;
  original_filename: string;
  content_type: string;
  image_url: string;
  original_image_url?: string;
  image_space?: "original" | "enhanced";
  width?: number | null;
  height?: number | null;
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

export interface AiVisionResult {
  run_id: string;
  question_id: string;
  page_id: string;
  question_no: string;
  marks: number[];
  steps: Array<{
    step_id: string;
    step_no: number;
    title: string;
    max_marks: number;
    awarded_marks: number;
  }>;
  awarded_marks: number;
  max_marks: number;
  x: number;
  y: number;
  width: number;
  height: number;
  // Reserved for a future rationale view. Do not render this in the current UI.
  reasoning?: string;
}

export interface AiVisionAcceptResponse {
  question: Question;
  annotation: Annotation;
}

export type AgentJobStatus =
  | "queued"
  | "extracting"
  | "evaluating"
  | "ready"
  | "ignored"
  | "failed"
  | "completed";

export type AgentReviewStatus =
  | "queued"
  | "evaluating"
  | "ready"
  | "accepted"
  | "rejected"
  | "error";

export interface AgentReview {
  id: string;
  question_id: string;
  question_no: string;
  question_text: string;
  page_id: string | null;
  question_order: number;
  cornerstone_question_no: number;
  area_count: number;
  area_urls: string[];
  enhanced_image_url: string | null;
  bbox: { x: number; y: number; w: number; h: number } | null;
  run_id: string | null;
  marks: number[] | null;
  awarded_marks: number | null;
  max_marks: number;
  status: AgentReviewStatus;
  error: string | null;
}

export interface AgentJob {
  enabled: boolean;
  id?: string;
  cornerstone_job_id?: string | null;
  cornerstone_status_url?: string | null;
  status?: AgentJobStatus;
  expected_questions?: number;
  detected_questions?: number | null;
  processed_questions?: number;
  ready_questions?: number;
  accepted_questions?: number;
  rejected_questions?: number;
  error?: string | null;
  reviews: AgentReview[];
}
