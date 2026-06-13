import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Evaluation, QuestionPaper } from "../types";

interface DataManagerProps {
  onOpenEvaluation: (id: string) => void;
}

const samplePaper = {
  paper_code: "ENG-10-A",
  subject_code: "ENG",
  subject_name: "English",
  class_code: "10",
  version: 1,
  status: "active",
  questions: [
    {
      question_no: "Q1",
      question_text: "Summarize the central idea of the passage.",
      max_marks: 5,
      question_type: "Long Answer",
      display_order: 1,
      reference_solution: "A concise summary covering the central idea.",
      steps: [
        {
          step_no: 1,
          title: "Main idea",
          description: "Identifies the central idea.",
          max_marks: 2,
        },
        {
          step_no: 2,
          title: "Supporting details",
          description: "Includes relevant supporting details.",
          max_marks: 2,
        },
        {
          step_no: 3,
          title: "Clarity",
          description: "Uses clear and concise language.",
          max_marks: 1,
        },
      ],
    },
  ],
};

export function DataManager({ onOpenEvaluation }: DataManagerProps) {
  const [papers, setPapers] = useState<QuestionPaper[]>([]);
  const [paperJson, setPaperJson] = useState(
    JSON.stringify(samplePaper, null, 2),
  );
  const [paperMessage, setPaperMessage] = useState("");
  const [submissionMessage, setSubmissionMessage] = useState("");
  const [busy, setBusy] = useState<"paper" | "submission" | null>(null);

  const loadPapers = useCallback(
    () =>
      api<QuestionPaper[]>("/question-papers")
        .then(setPapers)
        .catch((error: Error) => setPaperMessage(error.message)),
    [],
  );

  useEffect(() => {
    void loadPapers();
  }, [loadPapers]);

  const createPaper = async (event: FormEvent) => {
    event.preventDefault();
    setBusy("paper");
    setPaperMessage("");
    try {
      const payload = JSON.parse(paperJson) as Record<string, unknown>;
      const result = await api<QuestionPaper>("/question-papers", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setPaperMessage(`Created paper ${result.paper_code}.`);
      await loadPapers();
    } catch (error) {
      setPaperMessage(
        error instanceof Error ? error.message : "Unable to create paper",
      );
    } finally {
      setBusy(null);
    }
  };

  const createSubmission = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy("submission");
    setSubmissionMessage("");
    const form = event.currentTarget;
    const formData = new FormData(form);
    try {
      const result = await api<Evaluation>("/submissions", {
        method: "POST",
        body: formData,
      });
      setSubmissionMessage(
        `Created submission for ${result.student_id}. Opening evaluation...`,
      );
      form.reset();
      onOpenEvaluation(result.evaluation_id);
    } catch (error) {
      setSubmissionMessage(
        error instanceof Error ? error.message : "Unable to upload submission",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="page data-page">
      <section className="page-intro">
        <div>
          <p className="eyebrow">Local data tools</p>
          <h1>Add papers and submissions</h1>
          <p className="muted">
            Everything is stored in the backend SQLite database and local upload
            directory.
          </p>
        </div>
      </section>

      <div className="data-grid">
        <section className="surface data-card">
          <div className="data-card-heading">
            <span className="step-number">01</span>
            <div>
              <h2>Create a question paper</h2>
              <p className="muted">
                Edit the JSON template. Step marks must total each question's
                maximum.
              </p>
            </div>
          </div>
          <form onSubmit={createPaper}>
            <label>
              Question paper JSON
              <textarea
                className="json-editor"
                onChange={(event) => setPaperJson(event.target.value)}
                spellCheck={false}
                value={paperJson}
              />
            </label>
            {paperMessage && <p className="form-message">{paperMessage}</p>}
            <button className="button-primary" disabled={busy === "paper"}>
              {busy === "paper" ? "Creating..." : "Create paper"}
            </button>
          </form>
        </section>

        <div className="data-side-column">
          <section className="surface data-card">
            <div className="data-card-heading">
              <span className="step-number">02</span>
              <div>
                <h2>Upload a student submission</h2>
                <p className="muted">
                  Images are ordered by filename selection and become answer
                  sheet pages.
                </p>
              </div>
            </div>
            <form className="stacked-form" onSubmit={createSubmission}>
              <div className="form-row">
                <label>
                  Student ID
                  <input name="student_id" placeholder="STU002" required />
                </label>
                <label>
                  Student name
                  <input name="student_name" placeholder="Student name" />
                </label>
              </div>
              <label>
                Question paper code
                <select name="paper_code" required>
                  <option value="">Select a paper</option>
                  {papers.map((paper) => (
                    <option key={paper.id} value={paper.paper_code}>
                      {paper.paper_code} · {paper.subject_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Evaluation batch
                <input
                  defaultValue="June 2026"
                  name="evaluation_batch"
                  placeholder="June 2026"
                />
              </label>
              <label className="file-drop">
                <span>Answer sheet images</span>
                <input
                  accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                  multiple
                  name="images"
                  required
                  type="file"
                />
                <small>PNG, JPG, WebP, GIF or SVG · maximum 15 MB each</small>
              </label>
              {submissionMessage && (
                <p className="form-message">{submissionMessage}</p>
              )}
              <button
                className="button-primary"
                disabled={busy === "submission"}
              >
                {busy === "submission"
                  ? "Uploading..."
                  : "Create submission"}
              </button>
            </form>
          </section>

          <section className="surface data-card paper-list">
            <h2>Available paper codes</h2>
            {papers.map((paper) => (
              <div className="paper-list-row" key={paper.id}>
                <div>
                  <strong>{paper.paper_code}</strong>
                  <small>
                    {paper.subject_name} · Class {paper.class_code}
                  </small>
                </div>
                <span>
                  {paper.total_questions} Q · {paper.maximum_marks} marks
                </span>
              </div>
            ))}
          </section>
        </div>
      </div>
    </main>
  );
}
