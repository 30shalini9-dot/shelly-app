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
  AiVisionAcceptResponse,
  AiVisionResult,
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

interface AiResultCardProps {
  result: AiVisionResult;
  accepting: boolean;
  onAccept: () => void;
  onReject: () => void;
}

type DrawingTool = "pen" | "eraser" | "text";

interface DrawingStroke {
  id: string;
  kind: "stroke";
  color: string;
  width: number;
  points: Array<{ x: number; y: number }>;
}

interface DrawingText {
  id: string;
  kind: "text";
  color: string;
  x: number;
  y: number;
  text: string;
}

type DrawingItem = DrawingStroke | DrawingText;

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
const AI_TOTAL_ANNOTATION_PREFIX = "TAI|";
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
  if (
    text.startsWith(TOTAL_ANNOTATION_PREFIX) ||
    text.startsWith(AI_TOTAL_ANNOTATION_PREFIX)
  ) {
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

function loadExportImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Unable to load an answer-sheet page."));
    image.crossOrigin = "anonymous";
    image.src = src;
  });
}

function canvasToJpegBytes(canvas: HTMLCanvasElement) {
  const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
  const binary = atob(dataUrl.slice(dataUrl.indexOf(",") + 1));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function createImagePdf(
  pages: Array<{ bytes: Uint8Array; width: number; height: number }>,
) {
  const encoder = new TextEncoder();
  const objects: Uint8Array[] = [];
  const addObject = (parts: Array<string | Uint8Array>) => {
    const length = parts.reduce(
      (total, part) =>
        total + (typeof part === "string" ? encoder.encode(part).length : part.length),
      0,
    );
    const object = new Uint8Array(length);
    let offset = 0;
    for (const part of parts) {
      const bytes = typeof part === "string" ? encoder.encode(part) : part;
      object.set(bytes, offset);
      offset += bytes.length;
    }
    objects.push(object);
    return objects.length;
  };

  const catalogId = addObject([""]);
  const pagesId = addObject([""]);
  const pageIds: number[] = [];
  for (const page of pages) {
    const imageId = addObject([
      `<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.bytes.length} >>\nstream\n`,
      page.bytes,
      "\nendstream",
    ]);
    const content = encoder.encode(
      `q\n${page.width} 0 0 ${page.height} 0 0 cm\n/Im0 Do\nQ\n`,
    );
    const contentId = addObject([
      `<< /Length ${content.length} >>\nstream\n`,
      content,
      "endstream",
    ]);
    pageIds.push(
      addObject([
        `<< /Type /Page /Parent ${pagesId} 0 R /MediaBox [0 0 ${page.width} ${page.height}] /Resources << /XObject << /Im0 ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`,
      ]),
    );
  }
  objects[catalogId - 1] = encoder.encode(
    `<< /Type /Catalog /Pages ${pagesId} 0 R >>`,
  );
  objects[pagesId - 1] = encoder.encode(
    `<< /Type /Pages /Kids [${pageIds
      .map((id) => `${id} 0 R`)
      .join(" ")}] /Count ${pageIds.length} >>`,
  );

  const chunks: Uint8Array[] = [encoder.encode("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")];
  const offsets = [0];
  let byteOffset = chunks[0].length;
  objects.forEach((object, index) => {
    offsets.push(byteOffset);
    const wrapped = new Uint8Array(
      encoder.encode(`${index + 1} 0 obj\n`).length +
        object.length +
        encoder.encode("\nendobj\n").length,
    );
    const prefix = encoder.encode(`${index + 1} 0 obj\n`);
    const suffix = encoder.encode("\nendobj\n");
    wrapped.set(prefix);
    wrapped.set(object, prefix.length);
    wrapped.set(suffix, prefix.length + object.length);
    chunks.push(wrapped);
    byteOffset += wrapped.length;
  });
  const xrefOffset = byteOffset;
  const xref = [
    `xref\n0 ${objects.length + 1}\n`,
    "0000000000 65535 f \n",
    ...offsets
      .slice(1)
      .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`),
    `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`,
  ].join("");
  chunks.push(encoder.encode(xref));
  const pdfBuffer = new ArrayBuffer(
    chunks.reduce((total, chunk) => total + chunk.length, 0),
  );
  const pdfBytes = new Uint8Array(pdfBuffer);
  let pdfOffset = 0;
  for (const chunk of chunks) {
    pdfBytes.set(chunk, pdfOffset);
    pdfOffset += chunk.length;
  }
  return new Blob([pdfBuffer], { type: "application/pdf" });
}

function drawRoundedRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
  context.fill();
  context.stroke();
}

function createAnswerSheetCover(
  evaluation: Evaluation,
  progress: Progress,
  detailedQuestions: Question[],
) {
  const canvas = document.createElement("canvas");
  canvas.width = 1240;
  canvas.height = 1754;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Unable to prepare the answer-sheet cover.");

  const centerX = canvas.width / 2;
  const awardedMarks = progress.total_marks;
  const maximumMarks = progress.maximum_marks;
  const percentage =
    maximumMarks > 0 ? (awardedMarks / maximumMarks) * 100 : 0;
  const rows = detailedQuestions.flatMap((item) =>
    (item.steps || []).map((step) => ({
      questionNo: item.question_no,
      stepNo: step.step_no,
      maximum: step.max_marks,
      awarded: step.awarded_marks,
    })),
  );

  context.fillStyle = "#f4f8f8";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#102b45";
  context.fillRect(0, 0, canvas.width, 270);
  context.fillStyle = "#0d8f85";
  context.fillRect(0, 260, canvas.width, 10);

  context.beginPath();
  context.arc(1080, 50, 230, 0, Math.PI * 2);
  context.fillStyle = "rgba(41, 184, 169, 0.16)";
  context.fill();
  context.beginPath();
  context.arc(1100, 70, 150, 0, Math.PI * 2);
  context.strokeStyle = "rgba(255, 255, 255, 0.16)";
  context.lineWidth = 3;
  context.stroke();

  context.textAlign = "center";
  context.fillStyle = "#72ddd3";
  context.font = "700 24px Arial, sans-serif";
  context.fillText("EVALUATED ANSWER SHEET", centerX, 70);
  context.fillStyle = "#ffffff";
  context.font = "800 58px Arial, sans-serif";
  context.fillText(
    evaluation.student_name || evaluation.student_id,
    centerX,
    145,
  );
  context.fillStyle = "rgba(255, 255, 255, 0.74)";
  context.font = "500 24px Arial, sans-serif";
  context.fillText(
    `${evaluation.subject_name}  |  Class ${evaluation.class_code}`,
    centerX,
    200,
  );

  const detailsY = 325;
  context.fillStyle = "#ffffff";
  context.strokeStyle = "#d6e3e4";
  context.lineWidth = 2;
  drawRoundedRect(context, 100, detailsY, 1040, 132, 24);
  const details = [
    ["Student ID", evaluation.student_id],
    ["Subject", evaluation.subject_name],
    ["Class", evaluation.class_code],
  ];
  details.forEach(([label, value], index) => {
    const x = 130 + index * 347;
    if (index > 0) {
      context.beginPath();
      context.moveTo(x - 30, detailsY + 28);
      context.lineTo(x - 30, detailsY + 104);
      context.strokeStyle = "#dfe9e9";
      context.stroke();
    }
    context.textAlign = "left";
    context.fillStyle = "#70808d";
    context.font = "700 18px Arial, sans-serif";
    context.fillText(label.toUpperCase(), x, detailsY + 45);
    context.fillStyle = "#172c4d";
    context.font = "700 25px Arial, sans-serif";
    context.fillText(value, x, detailsY + 84);
  });

  const cardY = 500;
  const cards = [
    ["MARKS SCORED", formatMark(awardedMarks), "#0d8f85"],
    ["TOTAL MARKS", formatMark(maximumMarks), "#172c4d"],
    ["ACHIEVED", `${formatMark(percentage)}%`, "#d28a28"],
  ];
  cards.forEach(([label, value, color], index) => {
    const x = 100 + index * 360;
    context.fillStyle = "#ffffff";
    context.strokeStyle = "#d6e3e4";
    context.lineWidth = 2;
    drawRoundedRect(context, x, cardY, 320, 154, 24);
    context.textAlign = "center";
    context.fillStyle = String(color);
    context.font = "800 48px Arial, sans-serif";
    context.fillText(String(value), x + 160, cardY + 72);
    context.fillStyle = "#70808d";
    context.font = "700 17px Arial, sans-serif";
    context.fillText(String(label), x + 160, cardY + 116);
  });

  context.textAlign = "center";
  context.fillStyle = "#172c4d";
  context.font = "800 30px Arial, sans-serif";
  context.fillText("Question and Step Marking Summary", centerX, 720);
  context.fillStyle = "#70808d";
  context.font = "500 18px Arial, sans-serif";
  context.fillText(
    "Detailed marks awarded for each evaluated step",
    centerX,
    754,
  );

  const tableX = 150;
  const tableY = 800;
  const tableWidth = 940;
  const headerHeight = 64;
  const availableHeight = 780;
  const rowHeight = Math.min(
    58,
    Math.max(25, (availableHeight - headerHeight) / Math.max(1, rows.length)),
  );
  const tableHeight = headerHeight + rows.length * rowHeight;
  context.fillStyle = "#ffffff";
  context.strokeStyle = "#cfdddf";
  context.lineWidth = 2;
  drawRoundedRect(context, tableX, tableY, tableWidth, tableHeight, 18);

  context.save();
  context.beginPath();
  context.roundRect(tableX, tableY, tableWidth, headerHeight, 18);
  context.clip();
  context.fillStyle = "#0b756f";
  context.fillRect(tableX, tableY, tableWidth, headerHeight);
  context.restore();

  const columns = [
    { label: "QUESTION NO.", x: tableX + 145 },
    { label: "STEP NO.", x: tableX + 380 },
    { label: "MAX MARKS", x: tableX + 615 },
    { label: "MARKS SCORED", x: tableX + 820 },
  ];
  context.fillStyle = "#ffffff";
  context.font = "800 18px Arial, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  columns.forEach((column) =>
    context.fillText(column.label, column.x, tableY + headerHeight / 2),
  );

  const rowFontSize = Math.min(22, Math.max(13, rowHeight * 0.4));
  rows.forEach((row, index) => {
    const y = tableY + headerHeight + index * rowHeight;
    context.fillStyle = index % 2 === 0 ? "#ffffff" : "#f1f7f7";
    context.fillRect(tableX + 1, y, tableWidth - 2, rowHeight);
    context.strokeStyle = "#e2ebec";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(tableX, y + rowHeight);
    context.lineTo(tableX + tableWidth, y + rowHeight);
    context.stroke();
    context.font = `700 ${rowFontSize}px Arial, sans-serif`;
    context.fillStyle = "#243b53";
    context.fillText(row.questionNo, columns[0].x, y + rowHeight / 2);
    context.fillText(`S${row.stepNo}`, columns[1].x, y + rowHeight / 2);
    context.fillText(
      formatMark(row.maximum),
      columns[2].x,
      y + rowHeight / 2,
    );
    context.fillStyle = "#08746c";
    context.fillText(
      row.awarded === null ? "-" : formatMark(row.awarded),
      columns[3].x,
      y + rowHeight / 2,
    );
  });

  context.textBaseline = "alphabetic";
  context.fillStyle = "#70808d";
  context.font = "500 16px Arial, sans-serif";
  context.fillText(
    `${evaluation.subject_code}  |  ${evaluation.question_paper_code}`,
    centerX,
    1688,
  );
  context.fillStyle = "#0d8f85";
  context.fillRect(centerX - 45, 1715, 90, 5);
  return canvas;
}

function drawExportTotal(
  context: CanvasRenderingContext2D,
  annotation: Annotation,
  pageWidth: number,
  pageHeight: number,
) {
  const summary = parseQuestionTotal(annotation.text);
  if (!summary) return;
  const scale = Math.max(0.8, pageWidth / 1100);
  const cardWidth = 172 * scale;
  const lineHeight = 22 * scale;
  const padding = 12 * scale;
  const cardHeight =
    padding * 2 + lineHeight * (summary.steps.length + 2);
  const isAiGenerated = annotation.text.startsWith(
    AI_TOTAL_ANNOTATION_PREFIX,
  );
  const rawX = annotation.x * pageWidth - (isAiGenerated ? cardWidth / 2 : 0);
  const rawY = annotation.y * pageHeight - (isAiGenerated ? cardHeight / 2 : 0);
  const x = Math.min(
    pageWidth - cardWidth - padding,
    Math.max(padding, rawX),
  );
  const y = Math.min(
    pageHeight - cardHeight - padding,
    Math.max(padding, rawY),
  );

  context.save();
  context.fillStyle = "rgba(244, 255, 252, 0.48)";
  context.strokeStyle = "rgba(7, 116, 108, 0.55)";
  context.lineWidth = Math.max(1, 1.5 * scale);
  drawRoundedRect(context, x, y, cardWidth, cardHeight, 10 * scale);

  const left = x + padding;
  const right = x + cardWidth - padding;
  let textY = y + padding + lineHeight * 0.72;
  context.fillStyle = "#17304d";
  context.font = `700 ${14 * scale}px Arial, sans-serif`;
  context.textAlign = "left";
  context.fillText(summary.questionNo, left, textY);

  context.font = `600 ${12 * scale}px Arial, sans-serif`;
  for (const step of summary.steps) {
    textY += lineHeight;
    context.fillStyle = "#075f59";
    context.textAlign = "left";
    context.fillText(`S${step.stepNo}`, left, textY);
    context.textAlign = "right";
    context.fillText(
      `${formatMark(step.awarded)}/${formatMark(step.max)}`,
      right,
      textY,
    );
  }

  textY += lineHeight;
  context.strokeStyle = "rgba(7, 116, 108, 0.28)";
  context.beginPath();
  context.moveTo(left, textY - lineHeight * 0.72);
  context.lineTo(right, textY - lineHeight * 0.72);
  context.stroke();
  context.fillStyle = "#17304d";
  context.font = `700 ${13 * scale}px Arial, sans-serif`;
  context.textAlign = "left";
  context.fillText("Total", left, textY);
  context.textAlign = "right";
  context.fillText(
    `${formatMark(summary.awarded)}/${formatMark(summary.max)}`,
    right,
    textY,
  );
  if (isAiGenerated) {
    context.fillStyle = "#ffffff";
    context.strokeStyle = "#075f59";
    context.beginPath();
    context.arc(right - 7 * scale, y + 12 * scale, 9 * scale, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.fillStyle = "#075f59";
    context.font = `800 ${7 * scale}px Arial, sans-serif`;
    context.textAlign = "center";
    context.fillText("AI", right - 7 * scale, y + 14.5 * scale);
  }
  context.restore();
}

function drawExportStep(
  context: CanvasRenderingContext2D,
  annotation: Annotation,
  pageWidth: number,
  pageHeight: number,
) {
  const stepLabel = annotation.text.match(/(?:^|\s)S(\d+)(?:\s|·|$)/)?.[1];
  if (!stepLabel) return;
  const scale = Math.max(0.8, pageWidth / 1100);
  const fontSize = 11 * scale;
  const paddingX = 10 * scale;
  const height = 30 * scale;
  const x = annotation.x * pageWidth;
  const y = annotation.y * pageHeight;
  context.save();
  context.font = `800 ${fontSize}px Arial, sans-serif`;
  const width = context.measureText(annotation.text).width + paddingX * 2;
  const left = Math.min(
    pageWidth - width - paddingX,
    Math.max(paddingX, x - height / 2),
  );
  const top = Math.min(
    pageHeight - height - paddingX,
    Math.max(paddingX, y - height / 2),
  );
  context.globalAlpha = 0.7;
  context.fillStyle = "rgba(255, 255, 255, 0.72)";
  context.strokeStyle = "rgba(158, 45, 55, 0.78)";
  context.lineWidth = Math.max(1.5, 1.8 * scale);
  drawRoundedRect(context, left, top, width, height, height / 2);
  context.fillStyle = "#9e2d37";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(annotation.text, left + width / 2, top + height / 2);
  context.restore();
}

function drawExportDrawings(
  context: CanvasRenderingContext2D,
  items: DrawingItem[],
  pageWidth: number,
  pageHeight: number,
) {
  for (const item of items) {
    context.save();
    context.fillStyle = item.color;
    context.strokeStyle = item.color;
    if (item.kind === "text") {
      context.font = `600 ${Math.max(14, pageWidth * 0.018)}px Arial, sans-serif`;
      context.textBaseline = "top";
      context.fillText(item.text, item.x * pageWidth, item.y * pageHeight);
    } else if (item.points.length > 1) {
      context.lineCap = "round";
      context.lineJoin = "round";
      context.lineWidth = Math.max(1.5, item.width * pageWidth);
      context.beginPath();
      item.points.forEach((point, index) => {
        const x = point.x * pageWidth;
        const y = point.y * pageHeight;
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      context.stroke();
    }
    context.restore();
  }
}

function AiResultCard({
  result,
  accepting,
  onAccept,
  onReject,
}: AiResultCardProps) {
  return (
    <div className="ai-result-card">
      <div className="ai-result-heading">
        <span className="ai-result-badge">AI</span>
        <strong>{result.question_no} suggested marks</strong>
      </div>
      <div className="ai-result-steps">
        {result.steps.map((step) => (
          <span key={step.step_id}>
            <small>
              S{step.step_no} · {step.title}
            </small>
            <strong>
              {formatMark(step.awarded_marks)}/{formatMark(step.max_marks)}
            </strong>
          </span>
        ))}
      </div>
      <div className="ai-result-total">
        <span>Total</span>
        <strong>
          {formatMark(result.awarded_marks)}/{formatMark(result.max_marks)}
        </strong>
      </div>
      <div className="ai-result-actions">
        <button
          className="ai-result-accept"
          disabled={accepting}
          onClick={onAccept}
          type="button"
        >
          {accepting ? "Accepting…" : "Accept marks"}
        </button>
        <button
          className="ai-result-reject"
          disabled={accepting}
          onClick={onReject}
          type="button"
        >
          Reject
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
  const isAiGenerated = annotation.text.startsWith(
    AI_TOTAL_ANNOTATION_PREFIX,
  );
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
      } ${isAiGenerated ? "ai-generated" : ""}`}
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
        const halfWidth = isAiGenerated
          ? event.currentTarget.offsetWidth / page.clientWidth / 2
          : 0;
        const halfHeight = isAiGenerated
          ? event.currentTarget.offsetHeight / page.clientHeight / 2
          : 0;
        const minX = halfWidth;
        const minY = halfHeight;
        const maxX = Math.max(
          minX,
          1 -
            event.currentTarget.offsetWidth / page.clientWidth +
            halfWidth,
        );
        const maxY = Math.max(
          minY,
          1 -
            event.currentTarget.offsetHeight / page.clientHeight +
            halfHeight,
        );
        drag.x = Math.min(
          maxX,
          Math.max(minX, drag.startX + deltaX / page.clientWidth),
        );
        drag.y = Math.min(
          maxY,
          Math.max(minY, drag.startY + deltaY / page.clientHeight),
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
          <span className="question-total-heading">
            {summary.questionNo}
            {isAiGenerated && <span className="question-total-ai">AI</span>}
          </span>
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
          {isAiGenerated && <span className="question-total-ai">AI</span>}
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
  const [pendingAiResult, setPendingAiResult] =
    useState<AiVisionResult | null>(null);
  const [acceptingAiResult, setAcceptingAiResult] = useState(false);
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
  const [drawingTool, setDrawingTool] = useState<DrawingTool | null>(null);
  const [drawingColor, setDrawingColor] = useState("#b4232f");
  const [drawingItems, setDrawingItems] = useState<
    Record<string, DrawingItem[]>
  >(() => {
    try {
      const saved = window.localStorage.getItem(
        `sheldon-drawings:${evaluationId}`,
      );
      return saved
        ? (JSON.parse(saved) as Record<string, DrawingItem[]>)
        : {};
    } catch {
      return {};
    }
  });
  const [aiSelection, setAiSelectionState] = useState<AiSelection | null>(null);
  const [questionCursor, setQuestionCursor] = useState({
    x: 0,
    y: 0,
    visible: false,
  });
  const [notice, setNotice] = useState("");
  const [markingWarning, setMarkingWarning] = useState("");
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [resetPaperOpen, setResetPaperOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [resettingPaper, setResettingPaper] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const aiSelectionRef = useRef<AiSelection | null>(null);
  const rightPanelRef = useRef<HTMLElement>(null);
  const totalTimersRef = useRef(new Map<string, number>());
  const markingWarningTimerRef = useRef<number | null>(null);
  const annotationMovePromisesRef = useRef(
    new Map<string, Promise<Annotation>>(),
  );
  const activeStrokeRef = useRef<{
    pageId: string;
    item: DrawingStroke;
  } | null>(null);
  const activeTextDragRef = useRef<{
    pageId: string;
    itemId: string;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const drawingStorageKey = `sheldon-drawings:${evaluationId}`;

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
    ] = await Promise.all([
      api<Evaluation>(`/evaluations/${evaluationId}`),
      api<Page[]>(`/evaluations/${evaluationId}/pages`),
      api<Question[]>(`/evaluations/${evaluationId}/questions`),
      api<Progress>(`/evaluations/${evaluationId}/progress`),
      api<Annotation[]>(`/evaluations/${evaluationId}/annotations`),
    ]);
    setEvaluation(evaluationData);
    setPages(pageData);
    setQuestions(questionData);
    setProgress(progressData);
    setAnnotations(annotationData);
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
    try {
      window.localStorage.setItem(
        drawingStorageKey,
        JSON.stringify(drawingItems),
      );
    } catch {
      setNotice("Unable to save drawing changes in this browser.");
    }
  }, [drawingItems, drawingStorageKey]);

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
    const request = api<Annotation>(
      `/evaluations/${evaluationId}/annotations/${annotationId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ x, y }),
      },
    );
    annotationMovePromisesRef.current.set(annotationId, request);
    try {
      const saved = await request;
      setAnnotations((current) =>
        current.map((annotation) =>
          annotation.annotation_id === annotationId ? saved : annotation,
        ),
      );
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
    } finally {
      if (annotationMovePromisesRef.current.get(annotationId) === request) {
        annotationMovePromisesRef.current.delete(annotationId);
      }
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

  const eraseAtPoint = (pageId: string, point: { x: number; y: number }) => {
    const threshold = 0.025;
    setDrawingItems((current) => ({
      ...current,
      [pageId]: (current[pageId] || []).filter((item) => {
        if (item.kind === "text") {
          return Math.hypot(item.x - point.x, item.y - point.y) > threshold * 2;
        }
        return !item.points.some(
          (candidate) =>
            Math.hypot(candidate.x - point.x, candidate.y - point.y) <=
            threshold,
        );
      }),
    }));
  };

  const beginDrawing = (
    event: PointerEvent<HTMLDivElement>,
    pageId: string,
  ) => {
    if (!drawingTool) return false;
    event.preventDefault();
    event.stopPropagation();
    const point = normalizedPoint(event);
    if (drawingTool === "eraser") {
      eraseAtPoint(pageId, point);
      return true;
    }
    if (drawingTool === "text") {
      const existingText = [...(drawingItems[pageId] || [])]
        .reverse()
        .find(
          (item): item is DrawingText =>
            item.kind === "text" &&
            Math.abs(item.x - point.x) <= 0.12 &&
            Math.abs(item.y - point.y) <= 0.035,
        );
      if (existingText) {
        event.currentTarget.setPointerCapture(event.pointerId);
        activeTextDragRef.current = {
          pageId,
          itemId: existingText.id,
          offsetX: point.x - existingText.x,
          offsetY: point.y - existingText.y,
        };
        return true;
      }
      const text = window.prompt("Text to place on the answer sheet");
      if (text?.trim()) {
        const item: DrawingText = {
          id: crypto.randomUUID(),
          kind: "text",
          color: drawingColor,
          x: point.x,
          y: point.y,
          text: text.trim(),
        };
        setDrawingItems((current) => ({
          ...current,
          [pageId]: [...(current[pageId] || []), item],
        }));
      }
      return true;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    const item: DrawingStroke = {
      id: crypto.randomUUID(),
      kind: "stroke",
      color: drawingColor,
      width: 0.004,
      points: [point],
    };
    activeStrokeRef.current = { pageId, item };
    setDrawingItems((current) => ({
      ...current,
      [pageId]: [...(current[pageId] || []), item],
    }));
    return true;
  };

  const moveDrawing = (
    event: PointerEvent<HTMLDivElement>,
    pageId: string,
  ) => {
    const textDrag = activeTextDragRef.current;
    if (textDrag?.pageId === pageId) {
      const point = normalizedPoint(event);
      setDrawingItems((current) => ({
        ...current,
        [pageId]: (current[pageId] || []).map((item) =>
          item.id === textDrag.itemId && item.kind === "text"
            ? {
                ...item,
                x: Math.min(0.98, Math.max(0, point.x - textDrag.offsetX)),
                y: Math.min(0.98, Math.max(0, point.y - textDrag.offsetY)),
              }
            : item,
        ),
      }));
      return true;
    }
    if (drawingTool === "eraser" && event.buttons === 1) {
      eraseAtPoint(pageId, normalizedPoint(event));
      return true;
    }
    const active = activeStrokeRef.current;
    if (!active || active.pageId !== pageId) return false;
    const point = normalizedPoint(event);
    active.item.points.push(point);
    setDrawingItems((current) => ({
      ...current,
      [pageId]: (current[pageId] || []).map((item) =>
        item.id === active.item.id
          ? { ...active.item, points: [...active.item.points] }
          : item,
      ),
    }));
    return true;
  };

  const finishDrawing = (event: PointerEvent<HTMLDivElement>) => {
    if (!activeStrokeRef.current && !activeTextDragRef.current) return false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    activeStrokeRef.current = null;
    activeTextDragRef.current = null;
    return true;
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
      formData.append("x", String(selection.x));
      formData.append("y", String(selection.y));
      formData.append("width", String(selection.width));
      formData.append("height", String(selection.height));
      formData.append("crop", crop, "answer-selection.png");
      const result = await api<AiVisionResult>(
        `/evaluations/${evaluationId}/ai-vision`,
        { method: "POST", body: formData },
      );
      setAiSelection(null);
      setToolMode(null);
      setPendingAiResult(result);
      setNotice("AI Vision marks are ready. Accept or reject the suggestion.");
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

  const acceptPendingAiResult = async () => {
    if (!pendingAiResult) return;
    setAcceptingAiResult(true);
    try {
      const result = await api<AiVisionAcceptResponse>(
        `/evaluations/${evaluationId}/ai-vision/accept`,
        {
          method: "POST",
          body: JSON.stringify({
            run_id: pendingAiResult.run_id,
            question_id: pendingAiResult.question_id,
            page_id: pendingAiResult.page_id,
            marks: pendingAiResult.marks,
            x: pendingAiResult.x,
            y: pendingAiResult.y,
            width: pendingAiResult.width,
            height: pendingAiResult.height,
          }),
        },
      );
      setPendingAiResult(null);
      await refreshQuestionState(result.question.question_id);
      expandQuestionTotal(result.annotation.annotation_id);
      setNotice(
        `${result.question.question_no} AI marks accepted: ${formatMark(
          result.question.awarded_marks,
        )}/${formatMark(result.question.max_marks)}.`,
      );
      await moveToNextQuestion(result.question.question_id);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to accept AI marks",
      );
    } finally {
      setAcceptingAiResult(false);
    }
  };

  const rejectPendingAiResult = async () => {
    if (!pendingAiResult) return;
    try {
      await api(`/evaluations/${evaluationId}/ai-vision/reject`, {
        method: "POST",
        body: JSON.stringify({ run_id: pendingAiResult.run_id }),
      });
      setPendingAiResult(null);
      setNotice("AI Vision marks rejected. No marks were changed.");
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to reject AI Vision marks",
      );
    }
  };

  const submitEvaluation = async () => {
    setNotice("");
    setActionMenuOpen(false);
    setSubmitting(true);
    try {
      await api(`/evaluations/${evaluationId}/submit`, { method: "POST" });
      onBack();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Unable to submit evaluation",
      );
      setSubmitting(false);
    }
  };

  const downloadMarkedAnswerSheet = async () => {
    if (!evaluation || !progress) return;
    setActionMenuOpen(false);
    setDownloading(true);
    setNotice("");
    try {
      await Promise.all(annotationMovePromisesRef.current.values());
      const latestAnnotations = await api<Annotation[]>(
        `/evaluations/${evaluationId}/annotations`,
      );
      const detailedQuestions = await Promise.all(
        questions.map((item) =>
          api<Question>(
            `/evaluations/${evaluationId}/questions/${item.question_id}`,
          ),
        ),
      );
      setAnnotations(latestAnnotations);
      const loadedPages = await Promise.all(
        pages.map(async (page) => ({
          page,
          image: await loadExportImage(`${API_BASE}${page.image_url}`),
        })),
      );
      if (loadedPages.length === 0) {
        throw new Error("No answer-sheet pages are available to download.");
      }
      const cover = createAnswerSheetCover(
        evaluation,
        progress,
        detailedQuestions,
      );
      const answerPages = loadedPages.map(({ page, image }) => {
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("Unable to prepare the answer-sheet download.");
        }
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(
          image,
          0,
          0,
          canvas.width,
          canvas.height,
        );
        latestAnnotations
          .filter(
            (annotation) =>
              annotation.page_id === page.page_id &&
              annotation.step_id !== null,
          )
          .forEach((annotation) =>
            drawExportStep(context, annotation, canvas.width, canvas.height),
          );
        latestAnnotations
          .filter(
            (annotation) =>
              annotation.page_id === page.page_id &&
              annotation.step_id === null,
          )
          .forEach((annotation) =>
            drawExportTotal(
              context,
              annotation,
              canvas.width,
              canvas.height,
            ),
          );
        drawExportDrawings(
          context,
          drawingItems[page.page_id] || [],
          canvas.width,
          canvas.height,
        );
        return {
          bytes: canvasToJpegBytes(canvas),
          width: canvas.width,
          height: canvas.height,
        };
      });
      const pdfPages = [
        {
          bytes: canvasToJpegBytes(cover),
          width: cover.width,
          height: cover.height,
        },
        ...answerPages,
      ];
      const blob = createImagePdf(pdfPages);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const student = (evaluation?.student_name || evaluation?.student_id || "student")
        .replace(/[^a-z0-9]+/gi, "-")
        .replace(/^-|-$/g, "")
        .toLowerCase();
      link.href = url;
      link.download = `${student || "student"}-marked-answer-sheet.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setNotice("Marked answer sheet downloaded.");
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to download the marked answer sheet",
      );
    } finally {
      setDownloading(false);
    }
  };

  const resetQuestionPaper = async () => {
    setResettingPaper(true);
    setNotice("");
    try {
      await api(`/evaluations/${evaluationId}/marks`, { method: "DELETE" });
      setResetPaperOpen(false);
      setAnnotations([]);
      setExpandedMarkId(null);
      setExpandedTotalIds(new Set());
      await loadOverview();
      if (question) await refreshQuestionState(question.question_id);
      setNotice("All marks and marking labels were reset.");
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to reset the question paper",
      );
    } finally {
      setResettingPaper(false);
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
        setActionMenuOpen(false);
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
        <div
          className="evaluation-actions"
          onClick={(event) => event.stopPropagation()}
        >
          <button
            className="button-primary submit-button"
            disabled={submitting}
            onClick={() => void submitEvaluation()}
            type="button"
          >
            {submitting ? "Submitting…" : "Submit evaluation"}
          </button>
          <button
            aria-expanded={actionMenuOpen}
            aria-haspopup="menu"
            aria-label="Open evaluation actions"
            className="button-primary evaluation-actions-toggle"
            onClick={() => setActionMenuOpen((open) => !open)}
            type="button"
          >
            ▾
          </button>
          {actionMenuOpen && (
            <div className="evaluation-actions-menu" role="menu">
              <button
                disabled={submitting}
                onClick={() => void submitEvaluation()}
                role="menuitem"
                type="button"
              >
                <strong>Submit evaluation</strong>
                <span>Complete and return to dashboard</span>
              </button>
              <button
                disabled={downloading}
                onClick={() => void downloadMarkedAnswerSheet()}
                role="menuitem"
                type="button"
              >
                <strong>{downloading ? "Preparing download…" : "Download"}</strong>
                <span>Answer sheet with question totals</span>
              </button>
              <button
                className="danger"
                onClick={() => {
                  setActionMenuOpen(false);
                  setResetPaperOpen(true);
                }}
                role="menuitem"
                type="button"
              >
                <strong>Reset question paper</strong>
                <span>Delete marks for every question</span>
              </button>
            </div>
          )}
        </div>
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
        <div className="question-legend">
          <span className="legend-viewed">Viewed</span>
          <span className="legend-current">Current / partial</span>
          <span className="legend-completed">Completed</span>
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
        <div className="drawing-tools" onClick={(event) => event.stopPropagation()}>
          <span>Draw</span>
          <button
            className={drawingTool === "pen" ? "active" : ""}
            onClick={() =>
              setDrawingTool((current) => (current === "pen" ? null : "pen"))
            }
            title="Pen"
            type="button"
          >
            Pen
          </button>
          <label title="Drawing color">
            <input
              aria-label="Drawing color"
              onChange={(event) => setDrawingColor(event.target.value)}
              type="color"
              value={drawingColor}
            />
          </label>
          <button
            className={drawingTool === "eraser" ? "active" : ""}
            onClick={() =>
              setDrawingTool((current) =>
                current === "eraser" ? null : "eraser",
              )
            }
            title="Eraser"
            type="button"
          >
            Erase
          </button>
          <button
            className={drawingTool === "text" ? "active" : ""}
            onClick={() =>
              setDrawingTool((current) => (current === "text" ? null : "text"))
            }
            title="Text"
            type="button"
          >
            Text
          </button>
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
          className={`answer-canvas ${
            toolMode || drawingTool ? "tool-active" : ""
          } ${drawingTool ? `tool-${drawingTool}` : ""}`}
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
              const selection =
                aiSelection?.pageId === page.page_id ? aiSelection : null;
              const pendingResult =
                pendingAiResult?.page_id === page.page_id
                  ? pendingAiResult
                  : null;
              return (
                <div className="answer-page-frame" key={page.page_id}>
                  <span className="page-number-label">
                    Page {page.page_number}
                  </span>
                  <div
                    className="answer-page"
                    onContextMenu={(event) => openMarkMenu(event, page.page_id)}
                    onPointerDown={(event) =>
                      beginDrawing(event, page.page_id) ||
                      beginAiSelection(event, page.page_id)
                    }
                    onPointerMove={(event) => {
                      if (!moveDrawing(event, page.page_id)) {
                        moveAiSelection(event, page.page_id);
                      }
                    }}
                    onPointerUp={(event) => {
                      if (!finishDrawing(event)) {
                        finishAiSelection(event, page.page_id);
                      }
                    }}
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
                    <svg
                      aria-hidden="true"
                      className="drawing-layer"
                      preserveAspectRatio="none"
                      viewBox="0 0 1 1"
                    >
                      {(drawingItems[page.page_id] || []).map((item) =>
                        item.kind === "stroke" ? (
                          <polyline
                            fill="none"
                            key={item.id}
                            points={item.points
                              .map((point) => `${point.x},${point.y}`)
                              .join(" ")}
                            stroke={item.color}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={item.width}
                          />
                        ) : (
                          <text
                            dominantBaseline="hanging"
                            fill={item.color}
                            fontSize="0.022"
                            fontWeight="600"
                            key={item.id}
                            x={item.x}
                            y={item.y}
                          >
                            {item.text}
                          </text>
                        ),
                      )}
                    </svg>
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
                    {pendingResult && (
                      <div
                        className="ai-result-response"
                        onClick={(event) => event.stopPropagation()}
                        onContextMenu={(event) => event.stopPropagation()}
                        style={{
                          left: `${Math.min(
                            0.82,
                            Math.max(
                              0.18,
                              pendingResult.x + pendingResult.width / 2,
                            ),
                          ) * 100}%`,
                          top: `${Math.min(
                            0.8,
                            Math.max(
                              0.2,
                              pendingResult.y + pendingResult.height / 2,
                            ),
                          ) * 100}%`,
                        }}
                      >
                        <AiResultCard
                          accepting={acceptingAiResult}
                          onAccept={() => void acceptPendingAiResult()}
                          onReject={() => void rejectPendingAiResult()}
                          result={pendingResult}
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
                if (pendingAiResult) {
                  setNotice("Accept or reject the current AI marks first.");
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
      {resetPaperOpen && (
        <div
          aria-labelledby="reset-paper-title"
          aria-modal="true"
          className="confirmation-backdrop"
          role="dialog"
        >
          <div className="confirmation-dialog">
            <strong id="reset-paper-title">Reset the entire question paper?</strong>
            <p>
              This will permanently delete all awarded marks and marking labels
              for every question. The uploaded answer sheet will remain.
            </p>
            <div>
              <button
                className="button-ghost"
                disabled={resettingPaper}
                onClick={() => setResetPaperOpen(false)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="button-danger"
                disabled={resettingPaper}
                onClick={() => void resetQuestionPaper()}
                type="button"
              >
                {resettingPaper ? "Resetting…" : "Reset question paper"}
              </button>
            </div>
          </div>
        </div>
      )}
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
