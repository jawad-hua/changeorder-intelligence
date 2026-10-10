"use client";

import { useMemo, useRef, useState } from "react";
import {
  Activity, AlertCircle, ArrowDownToLine, ArrowRight, BadgeCheck, Check,
  CheckCheck, CheckCircle2, ChevronRight, ClipboardCopy, CloudUpload,
  Download, FileCheck2, FileJson2, FileText, FileWarning, Files, Fingerprint,
  Layers3, LoaderCircle, LockKeyhole, Search, ShieldCheck, Sparkles, Image as ImageIcon, Eye,
  TriangleAlert, WandSparkles, X,
} from "lucide-react";

type FieldStatus = "supported" | "review" | "missing";
type FieldValue = string | number | null;
type ExtractedField = {
  value: FieldValue;
  confidence: number;
  status: FieldStatus;
  evidence: { quote: string; page: number | null } | null;
};
type Extraction = {
  document_name: string;
  fields: Record<string, ExtractedField>;
  warnings: string[];
  pages: number | null;
  requires_review: boolean;
  visuals?: {source: string; page: number | null; data_uri: string}[];
  ocr_text?: string | null;
};
type Failure = { document_name: string; status_code: number; detail: string };
type BatchResponse = { results: Extraction[]; failures: Failure[]; requested: number };
type Review = { value: string; note: string; reviewed_at: string; kind: "manual_review" };
type ReviewedDocument = { extraction: Extraction; reviews: Record<string, Review> };
type Filter = "all" | FieldStatus | "unverified";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_BATCH = 5;
const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"];
const FIELD_LABELS: Record<string, string> = {
  change_order_number: "Change order number", project_name: "Project name",
  contractor: "Contractor", client: "Client / owner", description: "Description of change",
  reason: "Reason for change", cost_impact: "Cost impact", currency: "Currency",
  schedule_impact_days: "Schedule impact (days)", request_date: "Request date",
  approval_status: "Approval status",
};

function checkFile(file: File): string | null {
  if (!ALLOWED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext)))
    return `${file.name}: only PDF, DOCX, TXT, JPG, PNG, WEBP, or TIFF are supported.`;
  if (!file.size) return `${file.name}: the file is empty.`;
  if (file.size > MAX_FILE_BYTES) return `${file.name}: exceeds the 10 MB limit.`;
  return null;
}

function saveFile(content: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function csvCell(value: unknown): string {
  let text = value == null ? "" : String(value);
  // Prevent spreadsheet formula injection from untrusted document text.
  if (/^\s*[=+@\-\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function displayValue(value: FieldValue): string {
  return value == null || value === "" ? "Not found in document" : String(value);
}

function statusIcon(status: FieldStatus) {
  if (status === "supported") return <Check size={12} />;
  if (status === "review") return <AlertCircle size={12} />;
  return <X size={12} />;
}

function makeExport(document: ReviewedDocument) {
  return {
    ...document.extraction,
    visuals: undefined, // Do not include inline base64 thumbnails in structured exports.
    visual_previews: document.extraction.visuals?.map(({ source, page }) => ({ source, page })) ?? [],
    human_reviews: document.reviews,
    review_summary: {
      reviewed_fields: Object.keys(document.reviews).length,
      outstanding_fields: Object.entries(document.extraction.fields)
        .filter(([key, field]) => field.status !== "supported" && !document.reviews[key]).length,
      // Human review never changes the machine's evidence-based status.
      note: "Human reviews are separate from machine evidence and must be checked against the original document.",
    },
  };
}

function reviewCounts(document: ReviewedDocument) {
  const values = Object.values(document.extraction.fields);
  const supported = values.filter((item) => item.status === "supported").length;
  const missing = values.filter((item) => item.status === "missing").length;
  const review = values.filter((item) => item.status === "review").length;
  const manual = Object.keys(document.reviews).length;
  const unresolved = Object.entries(document.extraction.fields).filter(
    ([key, field]) => field.status !== "supported" && !document.reviews[key],
  ).length;
  return { supported, missing, review, manual, unresolved, total: values.length };
}

function FieldCard({ fieldKey, field, review, isVisionText, onSave, onRemove }: {
  fieldKey: string;
  field: ExtractedField;
  review?: Review;
  isVisionText: boolean;
  onSave: (value: string, note: string) => void;
  onRemove: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(review?.value ?? (field.value == null ? "" : String(field.value)));
  const [note, setNote] = useState(review?.note ?? "");
  const [issue, setIssue] = useState("");
  const modified = !!review && review.value !== (field.value == null ? "" : String(field.value));
  const showEdit = () => {
    setDraft(review?.value ?? (field.value == null ? "" : String(field.value)));
    setNote(review?.note ?? "");
    setIssue("");
    setEditing(true);
  };
  const save = () => {
    const changed = draft.trim() !== (field.value == null ? "" : String(field.value));
    if (!draft.trim()) { setIssue("Enter a verified value from the original document."); return; }
    if (changed && !note.trim()) { setIssue("Add a review note explaining the correction."); return; }
    onSave(draft.trim(), note.trim());
    setEditing(false);
  };
  return <article className={`field-card ${review ? "field-card-reviewed" : ""}`}>
    <div className="field-topline">
      <span className="field-label">{FIELD_LABELS[fieldKey] ?? fieldKey.replaceAll("_", " ")}</span>
      <span className={`status status-${field.status}`}>{statusIcon(field.status)} {field.status}</span>
    </div>
    <div className={`field-primary ${field.value == null && !review ? "muted" : ""}`}>
      {review ? review.value : displayValue(field.value)}
    </div>
    {modified && <p className="original-value">AI extracted: {displayValue(field.value)}</p>}
    <div className="confidence-row"><span>AI confidence indicator</span><strong>{Math.round(field.confidence * 100)}%</strong></div>
    <div className="meter"><span className={`meter-bar meter-${field.status}`} style={{ width: `${field.confidence * 100}%` }} /></div>
    {field.evidence && <div className="evidence"><span className="evidence-title"><ShieldCheck size={14} /> {isVisionText ? "AI-transcribed evidence" : "Source evidence"} {field.evidence.page != null && <em>· Page {field.evidence.page}</em>}</span><p>“{field.evidence.quote}”</p></div>}
    {review && <div className="manual-badge"><BadgeCheck size={15} /><div><strong>Manually reviewed</strong><span>AI source status is unchanged · {new Date(review.reviewed_at).toLocaleString()}</span>{review.note && <p>{review.note}</p>}</div></div>}
    {field.status !== "supported" && !review && <p className="field-warning"><AlertCircle size={13} /> Check against original before using this value.</p>}
    {editing ? <div className="review-form">
      <label>Verified value<textarea rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Enter value from original document" /></label>
      <label>Reviewer note <span>(required when changing value)</span><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you verify or correct?" /></label>
      {issue && <div className="inline-error" role="alert">{issue}</div>}
      <p>Only confirm after checking the source document. This action is stored in this browser session.</p>
      <div className="field-actions"><button className="mini-primary" type="button" onClick={save}><Check size={14} /> Confirm review</button><button className="mini-quiet" type="button" onClick={() => setEditing(false)}>Cancel</button></div>
    </div> : <div className="field-actions"><button className="mini-quiet review-trigger" type="button" onClick={showEdit}>{review ? "Edit review" : "Verify / correct"}<ArrowRight size={13} /></button>{review && <button className="mini-quiet" type="button" onClick={onRemove}>Undo review</button>}</div>}
  </article>;
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [documents, setDocuments] = useState<ReviewedDocument[]>([]);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [active, setActive] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  const selected = documents[active] ?? null;
  const counts = selected ? reviewCounts(selected) : null;
  const allCounts = useMemo(() => documents.reduce((acc, doc) => {
    const c = reviewCounts(doc);
    acc.fields += c.total;
    acc.supported += c.supported;
    acc.unresolved += c.unresolved;
    acc.manual += c.manual;
    return acc;
  }, { fields: 0, supported: 0, unresolved: 0, manual: 0 }), [documents]);

  const visibleFields = useMemo(() => {
    if (!selected) return [];
    return Object.entries(selected.extraction.fields).filter(([key, field]) => {
      const matchesFilter = filter === "all" ||
        (filter === "unverified" ? field.status !== "supported" && !selected.reviews[key] : field.status === filter);
      const matchesSearch = `${FIELD_LABELS[key] ?? key} ${field.value ?? ""} ${selected.reviews[key]?.value ?? ""}`
        .toLowerCase().includes(search.trim().toLowerCase());
      return matchesFilter && matchesSearch;
    });
  }, [selected, filter, search]);

  function addFiles(incoming: FileList | File[]) {
    const candidates = Array.from(incoming);
    if (!candidates.length) return;
    const merged = [...files];
    for (const candidate of candidates) {
      const problem = checkFile(candidate);
      if (problem) { setError(problem); return; }
      if (!merged.some((f) => f.name === candidate.name && f.size === candidate.size && f.lastModified === candidate.lastModified)) merged.push(candidate);
    }
    if (merged.length > MAX_BATCH) { setError(`Select no more than ${MAX_BATCH} documents per batch.`); return; }
    setFiles(merged);
    setError("");
  }

  async function extract() {
    if (!files.length || busy) return;
    setBusy(true);
    setError("");
    setDocuments([]);
    setFailures([]);
    setActive(0);
    setFilter("all");
    setSearch("");
    try {
      const form = new FormData();
      for (const file of files) form.append("files", file);
      const response = await fetch(`${API}/api/v1/extract/batch`, { method: "POST", body: form });
      const data = await response.json() as BatchResponse & { detail?: unknown };
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (HTTP ${response.status}).`);
      if (!Array.isArray(data.results) || !Array.isArray(data.failures)) throw new Error("Invalid API response. Check that the updated backend is running.");
      setDocuments(data.results.map((extraction) => ({ extraction, reviews: {} })));
      setFailures(data.failures);
      if (!data.results.length) setError("No documents were processed. Review the file errors below.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cannot connect to the extraction service.");
    } finally { setBusy(false); }
  }

  function updateReview(key: string, value: string, note: string) {
    setDocuments((current) => current.map((doc, index) => index === active
      ? { ...doc, reviews: { ...doc.reviews, [key]: { value, note, kind: "manual_review", reviewed_at: new Date().toISOString() } } }
      : doc));
  }

  function removeReview(key: string) {
    setDocuments((current) => current.map((doc, index) => {
      if (index !== active) return doc;
      const reviews = { ...doc.reviews };
      delete reviews[key];
      return { ...doc, reviews };
    }));
  }

  function exportedData() {
    return documents.length === 1 ? makeExport(documents[0]) : {
      documents: documents.map(makeExport), failures,
      summary: { processed_documents: documents.length, failed_documents: failures.length, ...allCounts },
    };
  }

  function exportJson() {
    if (!documents.length) return;
    saveFile(JSON.stringify(exportedData(), null, 2), "changeorder-analysis.json", "application/json");
  }

  async function copyJson() {
    if (!documents.length) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(exportedData(), null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1700);
    } catch { setError("Clipboard blocked. Use the JSON download instead."); }
  }

  function exportCsv() {
    if (!documents.length) return;
    const rows: unknown[][] = [["Document", "Field", "AI value", "AI status", "AI confidence", "Evidence", "Page", "Human reviewed value", "Reviewer note", "Reviewed at"]];
    for (const doc of documents) {
      for (const [key, field] of Object.entries(doc.extraction.fields)) {
        const human = doc.reviews[key];
        rows.push([
          doc.extraction.document_name, FIELD_LABELS[key] ?? key, field.value, field.status,
          field.confidence, field.evidence?.quote ?? "", field.evidence?.page ?? "",
          human?.value ?? "", human?.note ?? "", human?.reviewed_at ?? "",
        ]);
      }
    }
    saveFile("\uFEFF" + rows.map((r) => r.map(csvCell).join(",")).join("\r\n"), "changeorder-analysis.csv", "text/csv;charset=utf-8");
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Layers3 size={22} strokeWidth={2.4} /></div><div><strong>CHANGEORDER</strong><span>INTELLIGENCE</span></div></div>
      <div className="side-section">WORKSPACE</div>
      <div className="side-active"><WandSparkles size={17} /><span>Extraction studio</span><ChevronRight size={15} className="push-right" /></div>
      <div className="side-caption">SOURCE-FIRST WORKFLOW</div>
      <div className="side-step"><div>01</div><span>Upload documents</span></div>
      <div className="side-step"><div>02</div><span>Inspect evidence</span></div>
      <div className="side-step"><div>03</div><span>Verify & export</span></div>
      <div className="sidebar-bottom"><div className="secure-emblem"><Fingerprint size={20} /></div><div><strong>Grounded by design</strong><p>Trace every extracted field to its source.</p></div></div>
    </aside>

    <div className="main-column">
      <header className="topbar"><div className="breadcrumbs">Workspace <ChevronRight size={14} /> <strong>Extraction studio</strong></div><div className="topbar-right"><span className="live-indicator" /><span>Document intelligence</span><span className="topbar-separator" /><ShieldCheck size={16} /></div></header>
      <main className="content">
        <section className="hero-panel">
          <div className="hero-content">
            <div className="eyebrow"><Sparkles size={15} /> THE INTELLIGENT DOCUMENT WORKSPACE</div>
            <h1>Every change.<br /><span>Clearly understood.</span></h1>
            <p>Convert construction change orders into structured, evidence-linked decisions. Extract multiple documents, verify uncertain fields, and export a transparent review trail.</p>
            <div className="hero-tags"><span><CheckCircle2 size={16} /> Source-backed insights</span><span><Files size={16} /> Batch ready</span><span><ImageIcon size={16} /> Photo OCR</span><span><LockKeyhole size={16} /> No file history</span></div>
          </div>
          <div className="hero-decoration" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="glass-symbol"><FileCheck2 size={50} strokeWidth={1.25} /><span><Check size={17} /></span></div><div className="floating-chip chip-one"><ShieldCheck size={15} /> Evidence-first</div><div className="floating-chip chip-two"><Activity size={15} /> Human-in-the-loop</div></div>
        </section>

        <section className="glass-panel upload-panel" aria-label="Upload documents">
          <div className="panel-heading"><div><div className="section-kicker"><span className="kicker-dot" /> NEW ANALYSIS</div><h2>Import your documents</h2><p>Add up to five PDFs, Word files, text files, or photos containing change orders.</p></div><div className="privacy-label"><LockKeyhole size={14} /> In-memory processing</div></div>
          <input ref={inputRef} type="file" multiple accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp,.tif,.tiff,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/*" hidden onChange={(event) => { if (event.target.files) addFiles(event.target.files); event.target.value = ""; }} />
          <div className={`drop-zone ${dragging ? "drag-over" : ""}`} role="button" tabIndex={0}
            aria-label="Choose documents or images for OCR" onClick={() => inputRef.current?.click()}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inputRef.current?.click(); } }}
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
            onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}>
            <div className="upload-orb"><CloudUpload size={30} /></div>
            <strong>Drop documents or photos here</strong>
            <p>Drag & drop, or <span>browse files</span> to get started</p>
            <div className="format-line"><span>PDF</span><span>DOCX</span><span>TXT</span><span>IMAGE OCR</span><em>10 MB per file · 5 files max</em></div>
          </div>
          {files.length > 0 && <div className="file-queue"><div className="queue-title"><span><Files size={15} /> Ready to process <strong>{files.length}/{MAX_BATCH}</strong></span><button type="button" disabled={busy} onClick={() => setFiles([])}>Clear all</button></div><div className="queue-list">{files.map((file, i) => <div className="queue-file" key={`${file.name}-${file.lastModified}-${i}`}><div className="queue-icon"><FileText size={18} /></div><div><strong>{file.name}</strong><span>{(file.size / 1024).toFixed(1)} KB</span></div><button type="button" aria-label={`Remove ${file.name}`} disabled={busy} onClick={() => setFiles((old) => old.filter((_, j) => j !== i))}><X size={16} /></button></div>)}</div></div>}
          <div className="upload-bottom"><p><ShieldCheck size={17} /> Files are processed without permanent API file storage. Uploaded photos go to Groq Vision; PDF/DOCX text goes to Groq extraction. Scanned PDFs and embedded images use optional local OCR. Only upload documents you are authorized to share.</p><button type="button" className="primary-btn" disabled={!files.length || busy} onClick={extract}>{busy ? <LoaderCircle size={18} className="spin" /> : <Sparkles size={18} />}{busy ? "Analyzing documents…" : `Analyze ${files.length ? files.length : ""} document${files.length === 1 ? "" : "s"}`}<ArrowRight size={17} /></button></div>
        </section>

        {error && <div className="error-panel" role="alert"><TriangleAlert size={19} /><div><strong>Action needed</strong><p>{error}</p></div></div>}
        {failures.length > 0 && <div className="error-panel"><FileWarning size={19} /><div><strong>{failures.length} document{failures.length !== 1 ? "s" : ""} could not be processed</strong>{failures.map((f, i) => <p key={`${f.document_name}-${i}`}><b>{f.document_name}</b> (HTTP {f.status_code}): {f.detail}</p>)}</div></div>}

        {documents.length > 0 && <section className="workspace-area" aria-label="Extraction results">
          <div className="workspace-title-row"><div><div className="eyebrow"><BadgeCheck size={15} /> DOCUMENTS PROCESSED</div><h2>Analysis workspace</h2><p>{documents.length} document{documents.length === 1 ? "" : "s"} processed · Inspect, verify and export your findings.</p></div><div className="export-actions"><button type="button" onClick={copyJson} title="Copy all results as JSON"><ClipboardCopy size={16} /> {copied ? "Copied" : "Copy"}</button><button type="button" onClick={exportCsv}><ArrowDownToLine size={16} /> CSV</button><button type="button" onClick={exportJson} className="export-primary"><FileJson2 size={16} /> JSON</button></div></div>
          {documents.length > 1 && <div className="document-tabs" aria-label="Choose a processed document" role="tablist">{documents.map((doc, index) => <button type="button" role="tab" aria-selected={active === index} key={`${doc.extraction.document_name}-${index}`} className={active === index ? "selected" : ""} onClick={() => { setActive(index); setFilter("all"); setSearch(""); }}><FileText size={16} /> <span title={doc.extraction.document_name}>{doc.extraction.document_name}</span><small>{reviewCounts(doc).unresolved ? `${reviewCounts(doc).unresolved} to review` : "Ready"}</small></button>)}</div>}
          {selected && counts && <>
            <div className="active-document"><div className="doc-thumbnail"><FileCheck2 size={23} /></div><div><strong>{selected.extraction.document_name}</strong><p>{selected.extraction.pages == null ? "DOCX · Page count not available" : /\.(png|jpe?g|webp|tiff?)$/i.test(selected.extraction.document_name) ? "Image · Groq Vision text" : `${selected.extraction.pages} page${selected.extraction.pages === 1 ? "" : "s"}`} · Evidence-linked extraction</p></div><span className="document-pill">{counts.total} fields</span></div>
            {(selected.extraction.visuals?.length ?? 0) > 0 && <section className="visuals-section" aria-label="Extracted images and OCR previews">
              <div className="visuals-heading"><div><span className="section-kicker"><ImageIcon size={15} /> SOURCE IMAGES</span><h3>Visual evidence</h3><p>Image previews remain in your browser session. Transcribed image text may contain errors; verify key figures against the original.</p></div><span className="visuals-count">{selected.extraction.visuals!.length} preview{selected.extraction.visuals!.length !== 1 ? "s" : ""}</span></div>
              <div className="visuals-grid">{selected.extraction.visuals!.map((asset, index) => <button className="visual-card" type="button" key={`${index}-${asset.source}`} onClick={() => setPreviewImage(asset.data_uri)} aria-label={`Enlarge ${asset.source}`}>
                <img src={asset.data_uri} alt={`${asset.source}${asset.page ? `, page ${asset.page}` : ""}`} />
                <span><ImageIcon size={15} /> {asset.source}{asset.page != null ? ` · Page ${asset.page}` : ""}<Eye size={15} /></span>
              </button>)}</div>
            </section>}
            {/\.(png|jpe?g|webp|tiff?)$/i.test(selected.extraction.document_name) && <div className="vision-disclosure" role="note"><AlertCircle size={16} /> Image text is interpreted by Groq Vision. Quotes are validated against its transcript, not independently against the image pixels. Check prices, dates and approvals against your original photo.</div>}
            {selected.extraction.ocr_text && <section className="ocr-transcript" aria-label="Recognized text from images">
              <div className="ocr-transcript-head"><div><span className="section-kicker"><Fingerprint size={14} /> { /\.(png|jpe?g|webp|tiff?)$/i.test(selected.extraction.document_name) ? "GROQ VISION TRANSCRIPT" : "LOCAL OCR TRANSCRIPT" }</span><h3>Text found inside images</h3></div><button type="button" onClick={() => navigator.clipboard.writeText(selected.extraction.ocr_text ?? "").catch(() => setError("Clipboard access denied. Use JSON export instead."))}><ClipboardCopy size={15} /> Copy text</button></div>
              <pre>{selected.extraction.ocr_text}</pre>
              <p>{/\.(png|jpe?g|webp|tiff?)$/i.test(selected.extraction.document_name) ? "This transcript was generated by Groq Vision, not validated against the original pixels. Check important figures and approvals in your photo." : "Local OCR can misread scanned text. Compare important amounts and approvals with the original document."}</p>
            </section>}
            <div className="stat-grid"><div className="stat-card"><span><Files size={16} /> Fields checked</span><strong>{counts.total}</strong><small>Data points</small></div><div className="stat-card success"><span><ShieldCheck size={16} /> Evidence-linked</span><strong>{counts.supported}</strong><small>Matched to extracted text</small></div><div className="stat-card caution"><span><AlertCircle size={16} /> Still need review</span><strong>{counts.unresolved}</strong><small>Manual confirmation pending</small></div><div className="stat-card purple"><span><CheckCheck size={16} /> Human reviewed</span><strong>{counts.manual}</strong><small>Reviewed this session</small></div></div>
            <div className={`insight-banner ${counts.unresolved === 0 && !selected.extraction.requires_review ? "banner-ready" : ""}`}>{counts.unresolved === 0 && !selected.extraction.requires_review ? <CheckCircle2 size={21} /> : <TriangleAlert size={21} />}<div><strong>{counts.unresolved === 0 && !selected.extraction.requires_review ? "Review queue is clear" : "Manual verification recommended"}</strong><p>{counts.unresolved === 0 && !selected.extraction.requires_review ? "No unreviewed ambiguous or missing fields remain. Review notes remain separate from original AI evidence. For images, verify the original pixels." : counts.unresolved > 0 ? `${counts.unresolved} field${counts.unresolved === 1 ? "" : "s"} require source-document checking. You can correct and confirm values below without altering the original AI extraction.` : "All values have source text, but processing warnings need your attention. Read the processing notes and check the original document."}</p></div></div>
            <div className="review-toolbar"><div className="filter-buttons">{(["all", "supported", "review", "missing", "unverified"] as Filter[]).map((tab) => <button type="button" key={tab} className={filter === tab ? "active" : ""} onClick={() => setFilter(tab)}>{tab === "all" ? "All fields" : tab === "unverified" ? "Review queue" : tab}</button>)}</div><label className="search-box"><Search size={17} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a field…" aria-label="Search fields" /></label></div>
            {visibleFields.length > 0 ? <div className="field-grid">{visibleFields.map(([key, field]) => <FieldCard key={`${active}-${key}`} fieldKey={key} field={field} review={selected.reviews[key]} isVisionText={/\.(png|jpe?g|webp|tiff?)$/i.test(selected.extraction.document_name)} onSave={(value, note) => updateReview(key, value, note)} onRemove={() => removeReview(key)} />)}</div> : <div className="empty-filter"><Search size={22} /><p>Nothing matches your current filter.</p><button type="button" onClick={() => { setSearch(""); setFilter("all"); }}>Show all fields</button></div>}
            {selected.extraction.warnings.length > 0 && <div className="warnings"><strong><AlertCircle size={16} /> Original processing notes</strong>{selected.extraction.warnings.map((warning, i) => <p key={`${i}-${warning}`}>{warning}</p>)}<small>Machine warnings remain in exports even when you add a human review.</small></div>}
            <div className="footnote"><ShieldCheck size={15} /> Confidence scores are heuristic indicators, not statistically calibrated probabilities. Human review is recorded separately and is never presented as source-verified AI output. Your reviews remain in memory until you leave or refresh this page; export them before closing.</div>
          </>}
        </section>}
        {previewImage && <div className="image-lightbox" role="dialog" aria-modal="true" aria-label="Image preview" onClick={() => setPreviewImage(null)}>
          <button type="button" className="lightbox-close" aria-label="Close image" onClick={() => setPreviewImage(null)}><X size={22} /></button>
          <img src={previewImage} alt="Enlarged document image preview" onClick={(event) => event.stopPropagation()} />
        </div>}
        <footer><span>© {new Date().getFullYear()} ChangeOrder Intelligence. All Rights Reserved.</span><span>Built for traceable decisions <span className="footer-diamond">✦</span></span></footer>
      </main>
    </div>
  </div>;
}
