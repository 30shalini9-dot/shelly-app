import {
  CSSProperties,
  MouseEvent,
  PointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { API_BASE, api } from "../api";
import type {
  AiVisionNote,
  Annotation,
  Evaluation,
  Page,
  Progress,
  Question,
  Step,
} from "../types";

interface EvaluationWorkspaceProps {
  evaluationId: string;
  onBack: () => void;
}

interface MarkMenuState {
  x: number;
  y: number;
  pageId: string;
  pageX: number;
  pageY: number;
}

interface AiSelection {
  pageId: string;
  startX: number;
  startY: number;
  x: number;
  y: number;
  width: number;
  height: number;
  status: "selecting" | "loading";
}

interface MarkAnnotationProps {
  annotation: Annotation;
  expanded: boolean;
  onExpand: () => void;
}

interface AiNoteCardProps {
  note: AiVisionNote;
  onDelete: () => void;
  onSave: () => void;
  saveLabel?: string;
}

interface QuestionTotalSummary {
  questionNo: string;
  steps: Array<{
    stepNo: number;
    awarded: number;
    max: number;
  }>;
  awarded: number;
  max: number;
}

const TOTAL_ANNOTATION_PREFIX = "T|";
const LEGACY_TOTAL_ANNOTATION_PREFIX = "TOTAL:";

function formatMark(value: number) {
  return Number.isInteger(value)
    ? String(value)
    : String(Number(value.toFixed(2)));
}

function serializeQuestionTotal(question: Question) {
  const steps = (question.steps || [])
    .map(
      (step) =>
        `${formatMark(step.awarded_marks ?? 0)}/${formatMark(step.max_marks)}`,
    )
    .join(",");
  return `${TOTAL_ANNOTATION_PREFIX}${question.question_no}|${steps}|${formatMark(
    question.awarded_marks,
  )}/${formatMark(question.max_marks)}`;
}

function parseQuestionTotal(text: string): QuestionTotalSummary | null {
  if (text.startsWith(TOTAL_ANNOTATION_PREFIX)) {
    const [, questionNo, stepText, totalText] = text.split("|");
    const total = totalText?.split("/").map(Number);
    const steps = stepText
      ?.split(",")
      .filter(Boolean)
      .map((value, index) => {
        const [awarded, max] = value.split("/").map(Number);
        return { stepNo: index + 1, awarded, max };
      });
    if (
      !questionNo ||
      !steps ||
      !total ||
      total.length !== 2 ||
      steps.some(
        (step) =>
          !Number.isFinite(step.awarded) || !Number.isFinite(step.max),
      ) ||
      !Number.isFinite(total[0]) ||
      !Number.isFinite(total[1])
    ) {
      return null;
    }
    return {
      questionNo,
      steps,
      awarded: total[0],
      max: total[1],
    };
  }
  if (!text.startsWith(LEGACY_TOTAL_ANNOTATION_PREFIX)) return null;
  try {
    const summary = JSON.parse(
      text.slice(LEGACY_TOTAL_ANNOTATION_PREFIX.length),
    ) as QuestionTotalSummary;
    if (
      !summary.questionNo ||
      !Array.isArray(summary.steps) ||
      !Number.isFinite(summary.awarded) ||
      !Number.isFinite(summary.max)
    ) {
      return null;
    }
    return summary;
  } catch {
    return null;
  }
}

function AiNoteCard({
  note,
  onDelete,
  onSave,
  saveLabel = "Save",
}: AiNoteCardProps) {
  return (
    <div className="ai-note-card">
      <strong>AI Vision reference</strong>
      <p>{note.analysis}</p>
      <div className="ai-note-actions">
        <button className="ai-note-save" onClick={onSave} type="button">
          {saveLabel}
        </button>
        <button className="ai-note-delete" onClick={onDelete} type="button">
          Delete
        </button>
      </div>
    </div>
  );
}

function MarkAnnotation({
  annotation,
  expanded,
  onExpand,
}: MarkAnnotationProps) {
  const stepLabel = annotation.text.match(/(?:^|\s)S(\d+)(?:\s|·|$)/)?.[1];

  return (
    <button
      aria-expanded={expanded}
      aria-label={`Open mark details for step ${stepLabel || ""}`.trim()}
      className={`step-mark-annotation ${expanded ? "expanded" : ""}`}
      onClick={(event) => {
        event.stopPropagation();
        onExpand();
      }}
      onContextMenu={(event) => event.stopPropagation()}
      style={{
        left: `${annotation.x * 100}%`,
        top: `${annotation.y * 100}%`,
      }}
      type="button"
    >
      S{stepLabel || "?"}
      {expanded && (
        <span className="step-mark-tooltip">{annotation.text}</span>
      )}
    </button>
  );
}

interface QuestionTotalAnnotationProps {
  annotation: Annotation;
  expanded: boolean;
  onExpand: () => void;
  onMove: (x: number, y: number) => void;
}

function QuestionTotalAnnotation({
  annotation,
  expanded,
  onExpand,
  onMove,
}: QuestionTotalAnnotationProps) {
  const summary = parseQuestionTotal(annotation.text);
  const dragRef = useRef<{
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startX: number;
    startY: number;
    x: number;
    y: number;
    moved: boolean;
  } | null>(null);
  const suppressClickRef = useRef(false);
  if (!summary) return null;

  return (
    <button
      aria-expanded={expanded}
      className={`question-total-annotation ${
        expanded ? "expanded" : "collapsed"
      }`}
      onClick={(event) => {
        event.stopPropagation();
        if (suppressClickRef.current) {
          suppressClickRef.current = false;
          return;
        }
        onExpand();
      }}
      onContextMenu={(event) => event.stopPropagation()}
      onPointerCancel={(event) => {
        event.stopPropagation();
        dragRef.current = null;
      }}
      onPointerDown={(event) => {
        event.stopPropagation();
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        dragRef.current = {
          pointerId: event.pointerId,
          startClientX: event.clientX,
          startClientY: event.clientY,
          startX: annotation.x,
          startY: annotation.y,
          x: annotation.x,
          y: annotation.y,
          moved: false,
        };
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        const page = event.currentTarget.parentElement;
        if (
          !drag ||
          drag.pointerId !== event.pointerId ||
          !page ||
          page.clientWidth === 0 ||
          page.clientHeight === 0
        ) {
          return;
        }
        event.stopPropagation();
        const deltaX = event.clientX - drag.startClientX;
        const deltaY = event.clientY - drag.startClientY;
        if (!drag.moved && Math.hypot(deltaX, deltaY) < 4) return;
        drag.moved = true;
        const maxX = Math.max(
          0,
          1 - event.currentTarget.offsetWidth / page.clientWidth,
        );
        const maxY = Math.max(
          0,
          1 - event.currentTarget.offsetHeight / page.clientHeight,
        );
        drag.x = Math.min(
          maxX,
          Math.max(0, drag.startX + deltaX / page.clientWidth),
        );
        drag.y = Math.min(
          maxY,
          Math.max(0, drag.startY + deltaY / page.clientHeight),
        );
        event.currentTarget.style.left = `${drag.x * 100}%`;
        event.currentTarget.style.top = `${drag.y * 100}%`;
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        event.stopPropagation();
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.currentTarget.releasePointerCapture(event.pointerId);
        dragRef.current = null;
        if (drag.moved) {
          suppressClickRef.current = true;
          onMove(drag.x, drag.y);
        }
      }}
      style={{
        left: `${annotation.x * 100}%`,
        top: `${annotation.y * 100}%`,
      }}
      title="Drag to move this total card. Click to expand it for 2.5 seconds."
      type="button"
    >
      {expanded ? (
        <>
          <span className="question-total-heading">{summary.questionNo}</span>
          <span className="question-total-steps">
            {summary.steps.map((step) => (
              <span key={step.stepNo}>
                S{step.stepNo}
                <strong>
                  {formatMark(step.awarded)}/{formatMark(step.max)}
                </strong>
              </span>
            ))}
          </span>
          <span className="question-total-result">
            Total
            <strong>
              {formatMark(summary.awarded)}/{formatMark(summary.max)}
            </strong>
          </span>
        </>
      ) : (
        <>
          <strong>{summary.questionNo}:</strong>
          <span>
            {formatMark(summary.awarded)}/{formatMark(summary.max)}
          </span>
        </>
      )}
    </button>
  );
}

export function EvaluationWorkspace({
  evaluationId,
  onBack,
}: EvaluationWorkspaceProps) {
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [pages, setPages] = useState<Page[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [question, setQuestion] = useState<Question | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [aiNotes, setAiNotes] = useState<AiVisionNote[]>([]);
  const [pendingAiNote, setPendingAiNote] = useState<AiVisionNote | null>(null);
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [zoom, setZoom] = useState(0.82);
  const [rotation, setRotation] = useState(0);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [rightWidth, setRightWidth] = useState(300);
  const [resizingRight, setResizingRight] = useState(false);
  const [menu, setMenu] = useState<MarkMenuState | null>(null);
  const [expandedMarkId, setExpandedMarkId] = useState<string | null>(null);
  const [expandedTotalIds, setExpandedTotalIds] = useState<Set<string>>(
    new Set(),
  );
  const [toolMode, setToolMode] = useState<"ai-select" | null>(null);
  const [aiSelection, setAiSelectionState] = useState<AiSelection | null>(null);
  const [questionCursor, setQuestionCursor] = useState({
    x: 0,
    y: 0,
    visible: false,
  });
  const [notice, setNotice] = useState("");
  const [markingWarning, setMarkingWarning] = useState("");
  const [loading, setLoading] = useState(true);
  const aiSelectionRef = useRef<AiSelection | null>(null);
  const rightPanelRef = useRef<HTMLElement>(null);
  const totalTimersRef = useRef(new Map<string, number>());
  const markingWarningTimerRef = useRef<number | null>(null);

  const setAiSelection = (selection: AiSelection | null) => {
    aiSelectionRef.current = selection;
    setAiSelectionState(selection);
  };

  const loadOverview = useCallback(async () => {
    const [
      evaluationData,
      pageData,
      questionData,
      progressData,
      annotationData,
      aiNoteData,
    ] = await Promise.all([
      api<Evaluation>(`/evaluations/${evaluationId}`),
      api<Page[]>(`/evaluations/${evaluationId}/pages`),
      api<Question[]>(`/evaluations/${evaluationId}/questions`),
      api<Progress>(`/evaluations/${evaluationId}/progress`),
      api<Annotation[]>(`/evaluations/${evaluationId}/annotations`),
      api<AiVisionNote[]>(`/evaluations/${evaluationId}/ai-vision-notes`),
    ]);
    setEvaluation(evaluationData);
    setPages(pageData);
    setQuestions(questionData);
    setProgress(progressData);
    setAnnotations(annotationData);
    setAiNotes(aiNoteData);
    return questionData;
  }, [evaluationId]);

  const selectQuestion = useCallback(
    async (questionId: string) => {
      setNotice("");
      setMenu(null);
      setExpandedMarkId(null);
      setToolMode(null);
      setAiSelection(null);
      const detail = await api<Question>(
        `/evaluations/${evaluationId}/questions/${questionId}/focus`,
        { method: "PATCH" },
      );
      setQuestion(detail);
      const [questionData, progressData] = await Promise.all([
        api<Question[]>(`/evaluations/${evaluationId}/questions`),
        api<Progress>(`/evaluations/${evaluationId}/progress`),
      ]);
      setQuestions(questionData);
      setProgress(progressData);
    },
    [evaluationId],
  );

  useEffect(() => {
    loadOverview()
      .then((items) => {
        const firstIncomplete =
          items.find((item) => item.status !== "Completed") || items[0];
        if (firstIncomplete) return selectQuestion(firstIncomplete.question_id);
        return undefined;
      })
      .catch((error: Error) => setNotice(error.message))
      .finally(() => setLoading(false));
  }, [loadOverview, selectQuestion]);

  useEffect(() => {
    rightPanelRef.current?.scrollTo({ top: 0 });
  }, [question?.question_id]);

  useEffect(
    () => () => {
      totalTimersRef.current.forEach((timer) => window.clearTimeout(timer));
      if (markingWarningTimerRef.current) {
        window.clearTimeout(markingWarningTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!resizingRight) return undefined;
    const resize = (event: globalThis.PointerEvent) => {
      setRightWidth(
        Math.min(520, Math.max(240, window.innerWidth - event.clientX)),
      );
    };
    const stop = () => setResizingRight(false);
    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", stop, { once: true });
    return () => {
      window.removeEventListener("pointermove", resize);
      window.removeEventListener("pointerup", stop);
    };
  }, [resizingRight]);

  const activeStep = useMemo(() => {
    if (!question?.steps?.length) return null;
    return question.steps.find((step) => step.awarded_marks === null) || null;
  }, [question]);

  const showAlreadyMarkedWarning = () => {
    if (markingWarningTimerRef.current) {
      window.clearTimeout(markingWarningTimerRef.current);
    }
    setMenu(null);
    setMarkingWarning(
      `${question?.question_no || "This question"} has already been marked. Right click and Reset the question before marking it again.`,
    );
    markingWarningTimerRef.current = window.setTimeout(() => {
      setMarkingWarning("");
      markingWarningTimerRef.current = null;
    }, 3500);
  };

  const refreshQuestionState = async (questionId: string) => {
    const [detail, questionData, progressData, annotationData] =
      await Promise.all([
        api<Question>(`/evaluations/${evaluationId}/questions/${questionId}`),
        api<Question[]>(`/evaluations/${evaluationId}/questions`),
        api<Progress>(`/evaluations/${evaluationId}/progress`),
        api<Annotation[]>(`/evaluations/${evaluationId}/annotations`),
      ]);
    setQuestion(detail);
    setQuestions(questionData);
    setProgress(progressData);
    setAnnotations(annotationData);
    return detail;
  };

  const nextQuestionId = (questionId: string) => {
    const currentIndex = questions.findIndex(
      (item) => item.question_id === questionId,
    );
    return currentIndex >= 0 && currentIndex < questions.length - 1
      ? questions[currentIndex + 1].question_id
      : null;
  };

  const expandQuestionTotal = useCallback((annotationId: string) => {
    const existingTimer = totalTimersRef.current.get(annotationId);
    if (existingTimer) window.clearTimeout(existingTimer);
    setExpandedTotalIds((current) => new Set(current).add(annotationId));
    const timer = window.setTimeout(() => {
      setExpandedTotalIds((current) => {
        const next = new Set(current);
        next.delete(annotationId);
        return next;
      });
      totalTimersRef.current.delete(annotationId);
    }, 2500);
    totalTimersRef.current.set(annotationId, timer);
  }, []);

  const saveStepAnnotation = async (
    markedQuestion: Question,
    step: Step,
    marks: number,
    placement: MarkMenuState,
  ) => {
    await api<Annotation>(`/evaluations/${evaluationId}/annotations`, {
      method: "POST",
      body: JSON.stringify({
        question_id: markedQuestion.question_id,
        step_id: step.step_id,
        page_id: placement.pageId,
        text: `${markedQuestion.question_no} · S${step.step_no} · ${formatMark(
          marks,
        )}/${formatMark(step.max_marks)}`,
        x: placement.pageX,
        y: placement.pageY,
        width: 0.04,
        height: 0.04,
      }),
    });
  };

  const saveQuestionTotal = async (
    completedQuestion: Question,
    placement: MarkMenuState,
  ) => {
    const annotation = await api<Annotation>(
      `/evaluations/${evaluationId}/annotations`,
      {
        method: "POST",
        body: JSON.stringify({
          question_id: completedQuestion.question_id,
          step_id: null,
          page_id: placement.pageId,
          text: serializeQuestionTotal(completedQuestion),
          x: Math.min(0.82, placement.pageX + 0.045),
          y: Math.min(0.88, placement.pageY + 0.045),
          width: 0.18,
          height: 0.12,
        }),
      },
    );
    expandQuestionTotal(annotation.annotation_id);
  };

  const moveToNextQuestion = async (questionId: string) => {
    const nextId = nextQuestionId(questionId);
    if (nextId) await selectQuestion(nextId);
    else setNotice("All questions have been marked.");
  };

  const markStep = async (step: Step, marks: number) => {
    if (!question || !menu) return;
    if (question.status === "Completed") {
      showAlreadyMarkedWarning();
      return;
    }
    if (marks < 0 || marks > step.max_marks) {
      setNotice(`Marks must be between 0 and ${step.max_marks}.`);
      return;
    }
    const markedQuestion = question;
    const placement = menu;
    const questionId = question.question_id;
    setNotice("");
    setMenu(null);
    try {
      const updated = await api<Question>(
        `/evaluations/${evaluationId}/steps/${step.step_id}/marks`,
        {
          method: "POST",
          body: JSON.stringify({ awarded_marks: marks }),
        },
      );
      await saveStepAnnotation(markedQuestion, step, marks, placement);
      if (updated.status === "Completed") {
        await saveQuestionTotal(updated, placement);
      }
      await refreshQuestionState(questionId);
      if (updated.status === "Completed") {
        await moveToNextQuestion(questionId);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to save marks");
    }
  };

  const assignQuickMark = (marks: number | "custom") => {
    if (question?.status === "Completed" || !activeStep) {
      showAlreadyMarkedWarning();
      return;
    }
    if (marks === "custom") {
      const entered = window.prompt(
        `Marks for ${activeStep.title} (maximum ${activeStep.max_marks})`,
        "0",
      );
      if (entered === null || entered.trim() === "") return;
      const parsed = Number(entered);
      if (!Number.isFinite(parsed)) {
        setNotice("Enter a valid numeric mark.");
        return;
      }
      void markStep(activeStep, parsed);
      return;
    }
    void markStep(activeStep, marks);
  };

  const navigateQuestion = (direction: number) => {
    if (!question || questions.length === 0) return;
    const currentIndex = questions.findIndex(
      (item) => item.question_id === question.question_id,
    );
    const targetIndex = Math.min(
      questions.length - 1,
      Math.max(0, currentIndex + direction),
    );
    if (targetIndex !== currentIndex) {
      void selectQuestion(questions[targetIndex].question_id);
    }
  };

  const openMarkMenu = (
    event: MouseEvent<HTMLDivElement>,
    pageId: string,
  ) => {
    event.preventDefault();
    if (toolMode) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const pageX = (event.clientX - bounds.left) / bounds.width;
    const pageY = (event.clientY - bounds.top) / bounds.height;
    setMenu({
      x: event.clientX,
      y: event.clientY,
      pageId,
      pageX: Math.min(0.78, Math.max(0, pageX)),
      pageY: Math.min(0.92, Math.max(0, pageY)),
    });
  };

  const resetCurrentQuestion = async () => {
    if (!question) return;
    setMenu(null);
    try {
      await api(
        `/evaluations/${evaluationId}/questions/${question.question_id}/marks`,
        { method: "DELETE" },
      );
      await refreshQuestionState(question.question_id);
      setNotice(`${question.question_no} marks and labels were reset.`);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to reset question",
      );
    }
  };

  const moveQuestionTotal = async (
    annotationId: string,
    x: number,
    y: number,
  ) => {
    setAnnotations((current) =>
      current.map((annotation) =>
        annotation.annotation_id === annotationId
          ? { ...annotation, x, y }
          : annotation,
      ),
    );
    try {
      await api(`/evaluations/${evaluationId}/annotations/${annotationId}`, {
        method: "PATCH",
        body: JSON.stringify({ x, y }),
      });
    } catch (error) {
      const annotationData = await api<Annotation[]>(
        `/evaluations/${evaluationId}/annotations`,
      ).catch(() => null);
      if (annotationData) setAnnotations(annotationData);
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to move the question total",
      );
    }
  };

  const completeCurrentQuestion = async (mode: "full" | "total") => {
    if (!question || !menu) return;
    if (question.status === "Completed") {
      showAlreadyMarkedWarning();
      return;
    }
    const questionId = question.question_id;
    const placement = menu;
    setMenu(null);
    setNotice("");
    try {
      let updated = question;
      if (mode === "full") {
        updated = await api<Question>(
          `/evaluations/${evaluationId}/questions/${questionId}/full-marks`,
          { method: "POST" },
        );
      } else {
        for (const step of question.steps || []) {
          if (step.awarded_marks !== null) continue;
          updated = await api<Question>(
            `/evaluations/${evaluationId}/steps/${step.step_id}/marks`,
            {
              method: "POST",
              body: JSON.stringify({ awarded_marks: 0 }),
            },
          );
        }
      }
      await saveQuestionTotal(updated, placement);
      await refreshQuestionState(questionId);
      await moveToNextQuestion(questionId);
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : mode === "full"
            ? "Unable to award full marks"
            : "Unable to total the question",
      );
    }
  };

  const normalizedPoint = (
    event: PointerEvent<HTMLDivElement>,
  ): { x: number; y: number } => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
    };
  };

  const beginAiSelection = (
    event: PointerEvent<HTMLDivElement>,
    pageId: string,
  ) => {
    if (toolMode !== "ai-select") return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = normalizedPoint(event);
    setAiSelection({
      pageId,
      startX: point.x,
      startY: point.y,
      x: point.x,
      y: point.y,
      width: 0,
      height: 0,
      status: "selecting",
    });
  };

  const moveAiSelection = (
    event: PointerEvent<HTMLDivElement>,
    pageId: string,
  ) => {
    const selection = aiSelectionRef.current;
    if (
      toolMode !== "ai-select" ||
      !selection ||
      selection.status !== "selecting" ||
      selection.pageId !== pageId
    ) {
      return;
    }
    const point = normalizedPoint(event);
    setAiSelection({
      ...selection,
      x: Math.min(selection.startX, point.x),
      y: Math.min(selection.startY, point.y),
      width: Math.abs(point.x - selection.startX),
      height: Math.abs(point.y - selection.startY),
    });
  };

  const cropSelection = async (
    pageElement: HTMLDivElement,
    selection: AiSelection,
  ): Promise<Blob> => {
    const image = pageElement.querySelector("img");
    if (!image || !image.complete || !image.naturalWidth) {
      throw new Error("The answer-sheet image is not ready yet.");
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * selection.width));
    canvas.height = Math.max(
      1,
      Math.round(image.naturalHeight * selection.height),
    );
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Unable to prepare the selected image.");
    context.drawImage(
      image,
      image.naturalWidth * selection.x,
      image.naturalHeight * selection.y,
      image.naturalWidth * selection.width,
      image.naturalHeight * selection.height,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    const dataUrl = canvas.toDataURL("image/png");
    const response = await fetch(dataUrl);
    return response.blob();
  };

  const analyzeAiSelection = async (
    pageElement: HTMLDivElement,
    selection: AiSelection,
  ) => {
    if (!question) return;
    setAiSelection({ ...selection, status: "loading" });
    setNotice("AI Vision is reviewing the selected answer area...");
    try {
      const crop = await cropSelection(pageElement, selection);
      const formData = new FormData();
      formData.append("question_id", question.question_id);
      formData.append("page_id", selection.pageId);
      formData.append("question_text", question.question_text);
      formData.append("x", String(selection.x));
      formData.append("y", String(selection.y));
      formData.append("width", String(selection.width));
      formData.append("height", String(selection.height));
      formData.append("crop", crop, "answer-selection.png");
      const note = await api<AiVisionNote>(
        `/evaluations/${evaluationId}/ai-vision`,
        { method: "POST", body: formData },
      );
      setAiSelection(null);
      setToolMode(null);
      setPendingAiNote(note);
      setNotice("AI Vision analysis is ready. Save or delete the note.");
    } catch (error) {
      setAiSelection(null);
      setToolMode(null);
      setNotice(
        error instanceof Error ? error.message : "AI Vision analysis failed",
      );
    }
  };

  const finishAiSelection = (
    event: PointerEvent<HTMLDivElement>,
    pageId: string,
  ) => {
    const selection = aiSelectionRef.current;
    if (
      !selection ||
      selection.status !== "selecting" ||
      selection.pageId !== pageId
    ) {
      return;
    }
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (selection.width < 0.02 || selection.height < 0.02) {
      setAiSelection(null);
      setNotice("Drag a larger rectangle for AI Vision.");
      return;
    }
    setToolMode(null);
    void analyzeAiSelection(event.currentTarget, selection);
  };

  const toggleAiNote = (noteId: string) => {
    setExpandedNotes((current) => {
      const next = new Set(current);
      if (next.has(noteId)) next.delete(noteId);
      else next.add(noteId);
      return next;
    });
  };

  const savePendingAiNote = async () => {
    if (!pendingAiNote) return;
    try {
      const savedNote = await api<AiVisionNote>(
        `/evaluations/${evaluationId}/ai-vision-notes`,
        {
          method: "POST",
          body: JSON.stringify({
            question_id: pendingAiNote.question_id,
            page_id: pendingAiNote.page_id,
            analysis: pendingAiNote.analysis,
            x: pendingAiNote.x,
            y: pendingAiNote.y,
            width: pendingAiNote.width,
            height: pendingAiNote.height,
          }),
        },
      );
      setAiNotes((current) => [...current, savedNote]);
      setPendingAiNote(null);
      setNotice("AI Vision note saved.");
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to save AI Vision note",
      );
    }
  };

  const deleteAiNote = async (note: AiVisionNote, saved: boolean) => {
    try {
      if (saved) {
        await api<void>(
          `/evaluations/${evaluationId}/ai-vision-notes/${note.note_id}`,
          { method: "DELETE" },
        );
        setAiNotes((current) =>
          current.filter((item) => item.note_id !== note.note_id),
        );
        setExpandedNotes((current) => {
          const next = new Set(current);
          next.delete(note.note_id);
          return next;
        });
      } else {
        setPendingAiNote(null);
      }
      setNotice("AI Vision note deleted.");
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to delete AI Vision note",
      );
    }
  };

  const submitEvaluation = async () => {
    setNotice("");
    try {
      await api(`/evaluations/${evaluationId}/submit`, { method: "POST" });
      setNotice("Evaluation submitted successfully.");
      await loadOverview();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to submit evaluation",
      );
    }
  };

  if (loading || !evaluation || !progress) {
    return <div className="workspace-loading">Loading evaluation workspace...</div>;
  }

  const workspaceStyle = {
    "--right-panel-width": rightOpen ? `${rightWidth}px` : "0px",
  } as CSSProperties;

  return (
    <main
      className={`workspace ${leftOpen ? "" : "left-collapsed"} ${
        rightOpen ? "" : "right-collapsed"
      }`}
      onClick={() => {
        setMenu(null);
        setExpandedMarkId(null);
      }}
      style={workspaceStyle}
    >
      <header className="workspace-header">
        <button className="icon-button" onClick={onBack} title="Back" type="button">
          ←
        </button>
        <div className="workspace-title">
          <strong>
            {evaluation.student_name || "Unnamed student"} ·{" "}
            {evaluation.student_id}
          </strong>
          <span>
            {evaluation.subject_code} · {evaluation.subject_name} ·{" "}
            {evaluation.question_paper_code}
          </span>
        </div>
        <div className="header-metadata">
          <span>
            <small>Class</small>
            {evaluation.class_code}
          </span>
          <span>
            <small>Batch</small>
            {evaluation.evaluation_batch}
          </span>
          <span>
            <small>Questions</small>
            {progress.questions_evaluated}/{progress.total_questions}
          </span>
          <span>
            <small>Total</small>
            {progress.total_marks}/{progress.maximum_marks}
          </span>
        </div>
        <span
          className={`status status-${progress.status
            .toLowerCase()
            .replace(" ", "-")}`}
        >
          {progress.status}
        </span>
        <button
          className="button-primary submit-button"
          onClick={submitEvaluation}
          type="button"
        >
          Submit evaluation
        </button>
      </header>

      <aside className="left-panel side-panel">
        <div className="panel-heading">
          <div>
            <p className="panel-label">Questions</p>
            <strong>
              {progress.questions_evaluated}/{progress.total_questions} completed
            </strong>
          </div>
          <button
            className="panel-toggle"
            onClick={() => setLeftOpen(false)}
            title="Collapse questions"
            type="button"
          >
            ‹
          </button>
        </div>
        <div className="compact-question-grid">
          {questions.map((item) => {
            const stateClass =
              item.status === "Completed"
                ? "completed"
                : item.question_id === question?.question_id
                  ? "current"
                  : item.viewed
                    ? "viewed"
                    : "unseen";
            return (
              <button
                className={`compact-question ${stateClass}`}
                key={item.question_id}
                onClick={() => void selectQuestion(item.question_id)}
                title={`${item.question_no}: ${item.awarded_marks}/${item.max_marks} · ${item.status}`}
                type="button"
              >
                <strong>{item.question_no}</strong>
                <small>
                  {item.awarded_marks}/{item.max_marks}
                </small>
              </button>
            );
          })}
        </div>
        <div className="question-legend">
          <span className="legend-viewed">Viewed</span>
          <span className="legend-current">Current / partial</span>
          <span className="legend-completed">Completed</span>
        </div>
        <section className="left-progress-summary">
          <p className="panel-label">Evaluation progress</p>
          <div className="progress-track">
            <span style={{ width: `${progress.completion_percentage}%` }} />
          </div>
          <strong>{progress.completion_percentage}% complete</strong>
          <small>
            Viewed {progress.questions_viewed}/{progress.total_questions}
          </small>
        </section>
      </aside>

      {!leftOpen && (
        <button
          className="collapsed-panel-toggle left"
          onClick={() => setLeftOpen(true)}
          title="Expand questions"
          type="button"
        >
          ›
        </button>
      )}

      <section className="answer-workspace">
        <div className="viewer-toolbar">
          <button onClick={() => setZoom((value) => Math.max(0.35, value - 0.1))}>
            −
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))}>
            +
          </button>
          <span className="toolbar-divider" />
          <button onClick={() => setZoom(0.82)}>Fit width</button>
          <button onClick={() => setZoom(1)}>Actual size</button>
          <button onClick={() => setRotation((value) => (value + 90) % 360)}>
            Rotate
          </button>
          {toolMode === "ai-select" ? (
            <>
              <span className="viewer-instruction ai-active">
                Drag a rectangle over the answer for AI Vision
              </span>
              <button
                className="cancel-tool"
                onClick={() => {
                  setToolMode(null);
                  setAiSelection(null);
                }}
                type="button"
              >
                Cancel
              </button>
            </>
          ) : (
            <span className="viewer-instruction">
              Right-click an answer page for marks or AI Vision
            </span>
          )}
        </div>
        <div
          className={`answer-canvas ${toolMode ? "tool-active" : ""}`}
          onMouseEnter={() =>
            setQuestionCursor((cursor) => ({ ...cursor, visible: true }))
          }
          onMouseLeave={() =>
            setQuestionCursor((cursor) => ({ ...cursor, visible: false }))
          }
          onMouseMove={(event) =>
            setQuestionCursor({
              x: event.clientX,
              y: event.clientY,
              visible: true,
            })
          }
        >
          <div className="answer-pages">
            {pages.map((page) => {
              const pageAnnotations = annotations.filter(
                (annotation) => annotation.page_id === page.page_id,
              );
              const pageAiNotes = aiNotes.filter(
                (note) => note.page_id === page.page_id,
              );
              const selection =
                aiSelection?.pageId === page.page_id ? aiSelection : null;
              const pendingNote =
                pendingAiNote?.page_id === page.page_id ? pendingAiNote : null;
              return (
                <div className="answer-page-frame" key={page.page_id}>
                  <span className="page-number-label">
                    Page {page.page_number}
                  </span>
                  <div
                    className="answer-page"
                    onContextMenu={(event) => openMarkMenu(event, page.page_id)}
                    onPointerDown={(event) =>
                      beginAiSelection(event, page.page_id)
                    }
                    onPointerMove={(event) =>
                      moveAiSelection(event, page.page_id)
                    }
                    onPointerUp={(event) =>
                      finishAiSelection(event, page.page_id)
                    }
                    style={{
                      transform: `rotate(${rotation}deg)`,
                      width: `${zoom * 100}%`,
                    }}
                  >
                    <img
                      alt={`Answer sheet page ${page.page_number}`}
                      crossOrigin="anonymous"
                      draggable={false}
                      src={`${API_BASE}${page.image_url}`}
                    />
                    {pageAnnotations.map((annotation) =>
                      annotation.step_id === null ? (
                        <QuestionTotalAnnotation
                          annotation={annotation}
                          expanded={expandedTotalIds.has(
                            annotation.annotation_id,
                          )}
                          key={annotation.annotation_id}
                          onExpand={() =>
                            expandQuestionTotal(annotation.annotation_id)
                          }
                          onMove={(x, y) =>
                            void moveQuestionTotal(
                              annotation.annotation_id,
                              x,
                              y,
                            )
                          }
                        />
                      ) : (
                        <MarkAnnotation
                          annotation={annotation}
                          expanded={
                            expandedMarkId === annotation.annotation_id
                          }
                          key={annotation.annotation_id}
                          onExpand={() =>
                            setExpandedMarkId((current) =>
                              current === annotation.annotation_id
                                ? null
                                : annotation.annotation_id,
                            )
                          }
                        />
                      ),
                    )}
                    {pageAiNotes.map((note) => (
                      <div
                        className={`ai-note-marker ${
                          expandedNotes.has(note.note_id) ? "expanded" : ""
                        }`}
                        key={note.note_id}
                        onContextMenu={(event) => event.stopPropagation()}
                        onClick={(event) => event.stopPropagation()}
                        style={{
                          top: `${note.y * 100}%`,
                        }}
                      >
                        <button
                          className="ai-note-icon"
                          onClick={() => toggleAiNote(note.note_id)}
                          title="Open AI Vision note"
                          type="button"
                        >
                          AI
                        </button>
                        {expandedNotes.has(note.note_id) && (
                          <AiNoteCard
                            note={note}
                            onDelete={() => void deleteAiNote(note, true)}
                            onSave={() => toggleAiNote(note.note_id)}
                          />
                        )}
                      </div>
                    ))}
                    {pendingNote && (
                      <div
                        className="ai-note-response"
                        onClick={(event) => event.stopPropagation()}
                        onContextMenu={(event) => event.stopPropagation()}
                        style={{
                          top: `${Math.min(
                            0.82,
                            pendingNote.y + pendingNote.height,
                          ) * 100}%`,
                        }}
                      >
                        <AiNoteCard
                          note={pendingNote}
                          onDelete={() => void deleteAiNote(pendingNote, false)}
                          onSave={() => void savePendingAiNote()}
                        />
                      </div>
                    )}
                    {selection && (
                      <div
                        className={`ai-selection ${selection.status}`}
                        style={{
                          left: `${selection.x * 100}%`,
                          top: `${selection.y * 100}%`,
                          width: `${selection.width * 100}%`,
                          height: `${selection.height * 100}%`,
                        }}
                      >
                        <span>{selection.status === "loading" ? "AI…" : "AI"}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {questionCursor.visible && !toolMode && question && (
            <span
              className="evaluation-cursor"
              style={{
                left: questionCursor.x + 14,
                top: questionCursor.y + 14,
              }}
            >
              {question.question_no}
            </span>
          )}
        </div>
      </section>

      <aside
        className="right-panel side-panel"
        ref={rightPanelRef}
      >
        <div
          className="right-panel-resizer"
          aria-label="Resize question reference panel"
          aria-orientation="vertical"
          aria-valuemax={520}
          aria-valuemin={240}
          aria-valuenow={rightWidth}
          onPointerDown={(event) => {
            event.preventDefault();
            setResizingRight(true);
          }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            const change = event.key === "ArrowLeft" ? 20 : -20;
            setRightWidth((width) =>
              Math.min(520, Math.max(240, width + change)),
            );
          }}
          role="separator"
          tabIndex={0}
          title="Drag to resize question panel"
        />
        <div className="panel-heading">
          <div>
            <p className="panel-label">Question reference</p>
            <strong>{question?.question_no || "Question"}</strong>
          </div>
          <button
            className="panel-toggle"
            onClick={() => setRightOpen(false)}
            title="Collapse question reference"
            type="button"
          >
            ›
          </button>
        </div>
        {question && (
          <>
            <section>
              <h2>
                {question.question_no}. {question.question_text}
              </h2>
              <div className="question-facts">
                <span>
                  <small>Maximum</small>
                  <strong>{question.max_marks} marks</strong>
                </span>
                <span>
                  <small>Steps</small>
                  <strong>{question.total_steps}</strong>
                </span>
                <span>
                  <small>Type</small>
                  <strong>{question.question_type}</strong>
                </span>
              </div>
            </section>
            <section className="marking-guide read-only-guide">
              <div className="section-heading-row">
                <p className="panel-label">Step marking guide</p>
                <span>
                  {question.marked_steps}/{question.total_steps}
                </span>
              </div>
              {question.steps?.map((step) => (
                <article
                  className={`step-card ${
                    activeStep?.step_id === step.step_id ? "active" : ""
                  } ${step.awarded_marks !== null ? "complete" : ""}`}
                  key={step.step_id}
                >
                  <div className="step-card-heading">
                    <span className="step-check">
                      {step.awarded_marks !== null ? "✓" : step.step_no}
                    </span>
                    <div>
                      <strong>{step.title}</strong>
                      <small>{step.description}</small>
                    </div>
                    <span className="step-max">
                      {step.awarded_marks !== null
                        ? `${step.awarded_marks}/${step.max_marks}`
                        : `${step.max_marks} max`}
                    </span>
                  </div>
                </article>
              ))}
            </section>
            <section className="reference-solution">
              <p className="panel-label">Reference solution</p>
              <p>{question.reference_solution || "No reference solution provided."}</p>
            </section>
          </>
        )}
      </aside>

      {!rightOpen && (
        <button
          className="collapsed-panel-toggle right"
          onClick={() => setRightOpen(true)}
          title="Expand question reference"
          type="button"
        >
          ‹
        </button>
      )}

      {menu && (
        <div
          className="context-menu"
          onClick={(event) => event.stopPropagation()}
          style={{ left: menu.x, top: menu.y }}
        >
          <p>
            {question?.question_no} · Step {activeStep?.step_no ?? "complete"}
            <small>Max {activeStep?.max_marks ?? 0}</small>
          </p>
          {activeStep ? (
            <div className="context-mark-grid">
              {[0, 0.5, 1, 1.5, 2].map((mark) => (
                <button
                  disabled={mark > activeStep.max_marks}
                  key={mark}
                  onClick={() => assignQuickMark(mark)}
                  type="button"
                >
                  {mark}
                </button>
              ))}
              <button onClick={() => assignQuickMark("custom")} type="button">
                Custom
              </button>
            </div>
          ) : (
            <div className="context-complete-message">Question completed</div>
          )}
          <div className="context-action-grid">
            <button
              className="context-ai"
              onClick={() => {
                setMenu(null);
                if (pendingAiNote) {
                  setNotice("Save or delete the current AI Vision note first.");
                  return;
                }
                setToolMode("ai-select");
                setNotice("Drag a rectangle over the answer for AI Vision.");
              }}
              type="button"
            >
              AI Vision
            </button>
            <button
              className="context-success"
              onClick={() => void completeCurrentQuestion("full")}
              type="button"
            >
              Full marks
            </button>
            <button
              className="context-danger"
              onClick={() => void resetCurrentQuestion()}
              type="button"
            >
              Reset question
            </button>
            <button
              className="context-total"
              onClick={() => void completeCurrentQuestion("total")}
              type="button"
            >
              Do total
            </button>
          </div>
          <div className="context-nav">
            <button onClick={() => navigateQuestion(-1)} type="button">
              ← Previous
            </button>
            <button onClick={() => navigateQuestion(1)} type="button">
              Next →
            </button>
          </div>
        </div>
      )}

      {notice && <div className="toast">{notice}</div>}
      {markingWarning && (
        <div className="marking-warning-popup" role="alert">
          <div>
            <strong>Question already marked</strong>
            <span>{markingWarning}</span>
          </div>
          <button
            aria-label="Close warning"
            onClick={() => {
              if (markingWarningTimerRef.current) {
                window.clearTimeout(markingWarningTimerRef.current);
                markingWarningTimerRef.current = null;
              }
              setMarkingWarning("");
            }}
            type="button"
          >
            ×
          </button>
        </div>
      )}
    </main>
  );
}
