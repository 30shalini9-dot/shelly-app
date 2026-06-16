import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { EvaluationListItem } from "../types";

interface DashboardProps {
  onOpenEvaluation: (id: string) => void;
  notice?: string;
}

export function Dashboard({ notice, onOpenEvaluation }: DashboardProps) {
  const [evaluations, setEvaluations] = useState<EvaluationListItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const syncExtractingAgentJobs = useCallback(
    async (items: EvaluationListItem[]) => {
      const extracting = items.filter(
        (item) => item.agent_mode && item.agent_status === "extracting",
      );
      if (extracting.length === 0) return false;
      await Promise.all(
        extracting.map((item) =>
          api(`/evaluations/${item.evaluation_id}/agent/sync`, {
            method: "POST",
          }).catch(() => undefined),
        ),
      );
      return true;
    },
    [],
  );

  const loadEvaluations = useCallback(async (shouldApply: () => boolean = () => true) => {
    try {
      let items = await api<EvaluationListItem[]>("/evaluations");
      if (await syncExtractingAgentJobs(items)) {
        items = await api<EvaluationListItem[]>("/evaluations");
      }
      if (!shouldApply()) return;
      setEvaluations(items);
      setError("");
    } catch (requestError) {
      if (!shouldApply()) return;
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load evaluations",
      );
    } finally {
      if (!shouldApply()) return;
      setLoading(false);
    }
  }, [syncExtractingAgentJobs]);

  useEffect(() => {
    let active = true;
    void loadEvaluations(() => active);
    return () => {
      active = false;
    };
  }, [loadEvaluations]);

  useEffect(() => {
    const hasActiveAgentJob = evaluations.some(
      (item) =>
        item.agent_mode &&
        ["queued", "extracting", "evaluating"].includes(item.agent_status || ""),
    );
    if (!hasActiveAgentJob) return undefined;
    const timer = window.setInterval(() => void loadEvaluations(), 2500);
    return () => window.clearInterval(timer);
  }, [evaluations, loadEvaluations]);

  const filtered = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    if (!normalized) return evaluations;
    return evaluations.filter((item) =>
      [
        item.student_id,
        item.student_name,
        item.subject,
        item.question_paper_code,
        item.status,
      ]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(normalized)),
    );
  }, [evaluations, query]);

  const completed = evaluations.filter(
    (evaluation) => evaluation.status === "Completed",
  ).length;
  const inProgress = evaluations.filter(
    (evaluation) => evaluation.status === "In Progress",
  ).length;

  return (
    <main className="page dashboard-page">
      <section className="page-intro">
        <div>
          <p className="eyebrow">Evaluation dashboard</p>
          <h1>Student answer sheets</h1>
          <p className="muted">
            Review assigned submissions and continue work from the last saved
            question.
          </p>
        </div>
        <div className="summary-strip">
          <span>
            <strong>{evaluations.length}</strong>
            Assigned
          </span>
          <span>
            <strong>{inProgress}</strong>
            In progress
          </span>
          <span>
            <strong>{completed}</strong>
            Completed
          </span>
        </div>
      </section>

      {notice && <div className="dashboard-notice">{notice}</div>}

      <section className="surface table-surface">
        <div className="surface-toolbar">
          <div>
            <h2>Assigned evaluations</h2>
            <p className="muted">{filtered.length} records</p>
          </div>
          <label className="search-field">
            <span aria-hidden="true">⌕</span>
            <input
              aria-label="Search evaluations"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search student, subject or paper..."
              value={query}
            />
          </label>
        </div>

        {loading && <div className="empty-state">Loading evaluations...</div>}
        {error && <div className="empty-state form-error">{error}</div>}
        {!loading && !error && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Subject</th>
                  <th>Paper code</th>
                  <th>Questions</th>
                  <th>Status</th>
                  <th>Agent</th>
                  <th>Marks</th>
                  <th>Last updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((evaluation) => (
                  <tr key={evaluation.evaluation_id}>
                    <td>
                      <strong>{evaluation.student_name || "Unnamed student"}</strong>
                      <small>{evaluation.student_id}</small>
                    </td>
                    <td>{evaluation.subject}</td>
                    <td>
                      <code>{evaluation.question_paper_code}</code>
                    </td>
                    <td>{evaluation.total_questions}</td>
                    <td>
                      <span
                        className={`status status-${evaluation.status
                          .toLowerCase()
                          .replace(" ", "-")}`}
                      >
                        {evaluation.status}
                      </span>
                    </td>
                    <td>
                      {evaluation.agent_mode ? (
                        <span
                          className={`agent-status agent-status-${
                            evaluation.agent_status || "queued"
                          }`}
                        >
                          <span aria-hidden="true" />
                          {evaluation.agent_status === "ready"
                            ? "Review ready"
                            : evaluation.agent_status === "completed"
                              ? "Reviewed"
                              : evaluation.agent_status === "ignored"
                                ? "Skipped"
                                : evaluation.agent_status === "failed"
                                  ? "Needs attention"
                                  : evaluation.agent_status || "Queued"}
                        </span>
                      ) : (
                        <span className="muted">Manual</span>
                      )}
                    </td>
                    <td>
                      <strong>{evaluation.marks_awarded}</strong>
                      <span className="muted"> / {evaluation.maximum_marks}</span>
                    </td>
                    <td>{new Date(evaluation.updated_at).toLocaleString()}</td>
                    <td>
                      <button
                        className="button-secondary"
                        onClick={() =>
                          onOpenEvaluation(evaluation.evaluation_id)
                        }
                        type="button"
                      >
                        {evaluation.status === "Not Started"
                          ? "Review"
                          : evaluation.status === "Completed"
                            ? "View"
                            : "Continue"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="empty-state">No evaluations match this search.</div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
