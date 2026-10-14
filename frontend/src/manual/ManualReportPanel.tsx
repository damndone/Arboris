// v1.9.0 — writing a report by hand, without a language model. A draft starts
// from the run's computed evidence; the prose is the person's, the numbers
// stay read-only and cited. Every save is a new version linked to the one it
// revises, and exports carry that saved version with its evidence.

import { useEffect, useId, useRef, useState } from "react";
import { AnalysisDisclosure } from "../report/AnalysisDisclosure";
import { EvidenceToggle, ReportSources } from "../report/ReportSources";
import { reportDraft, reportExportUrl, reportHistory, saveReport, type Draft, type Report } from "./manualApi";
import { ReportReadingView, factLabel, factValue, markersIn } from "./ReportEvidence";
import "./manual.css";

const EXPORTS: Array<{ format: string; label: string }> = [
  { format: "html", label: "Export HTML" },
  { format: "docx", label: "Export DOCX" },
  { format: "tex", label: "Export TEX" },
  { format: "pdf-print", label: "Export print-ready HTML" },
];

const newSaveId = () => `mrpt_${crypto.randomUUID()}`;
const message = (reason: unknown) => (reason instanceof Error ? reason.message : String(reason));

export function ManualReportPanel({ projectRoot, runId }: { projectRoot: string; runId: string }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [history, setHistory] = useState<Report[]>([]);
  const [current, setCurrent] = useState<Report | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [facts, setFacts] = useState<string[]>([]);
  const [figures, setFigures] = useState<string[]>([]);
  const [reading, setReading] = useState(true);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // One id per unsaved edit: a retried save is the same save.
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const evidenceId = useId();
  const saveId = useRef(newSaveId());
  const pending = useRef(false);

  const edited = () => {
    setSaved(false);
    saveId.current = newSaveId();
  };
  const startFrom = (next: Draft) => {
    setDraft(next);
    setCurrent(null);
    setTitle(next.title);
    setText(next.text);
    setFacts(next.facts.map((fact) => fact.id));
    setFigures(next.figures.map((figure) => figure.artifact_id));
    edited();
  };
  const open = (report: Report) => {
    setCurrent(report);
    setTitle(report.title);
    setText(report.text);
    setFacts(report.facts.map((fact) => fact.id));
    setFigures(report.figures.map((figure) => figure.artifact_id));
    setSaved(true);
    saveId.current = newSaveId();
  };

  useEffect(() => {
    let live = true;
    setBusy(true);
    setError("");
    Promise.all([reportDraft(projectRoot, runId), reportHistory(projectRoot, runId)])
      .then(([first, past]) => {
        if (!live) return;
        startFrom(first);
        setHistory(past.reports);
      })
      .catch((reason) => live && setError(message(reason)))
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot, runId]);

  async function newDraft() {
    setBusy(true);
    setError("");
    try {
      startFrom(await reportDraft(projectRoot, runId));
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await saveReport(projectRoot, runId, {
        id: saveId.current,
        title,
        text,
        source_fingerprint: current?.source_fingerprint ?? draft.source_fingerprint,
        fact_ids: facts,
        figure_ids: figures,
        ...(current ? { parent_report_id: current.id } : {}),
      });
      open(result.record);
      setHistory((old) => [result.record, ...old.filter((report) => report.id !== result.record.id)]);
    } catch (reason) {
      setError(message(reason));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  const evidence = current?.facts ?? draft?.facts ?? [];
  const figureEvidence = current?.figures ?? draft?.figures ?? [];
  const limitations = current?.limitations ?? draft?.limitations ?? [];
  const choose = (list: string[], id: string, on: boolean) => (on ? [...list, id] : list.filter((value) => value !== id));

  const markers = markersIn(text, evidence);
  return (
    <section className="manual-panel mr" aria-label="Manual report">
      {error && <p role="alert">{error}</p>}
      <div className="report-document-layout">
        <fieldset className="report-document mr-doc" disabled={busy || !draft}>
          <legend className="ws-visually-hidden">Report</legend>
          <input
            className="mr-title"
            aria-label="Report title"
            maxLength={300}
            value={title}
            placeholder="Report title"
            onChange={(event) => {
              edited();
              setTitle(event.target.value);
            }}
          />
          <div className="mr-toolbar">
            <div className="mr-seg" role="group" aria-label="Report display">
              <button type="button" aria-pressed={reading} onClick={() => setReading(true)} title="How the report reads, with values filled in">Preview</button>
              <button type="button" aria-pressed={!reading} onClick={() => setReading(false)} title="Write and change the text">Edit text</button>
            </div>
            <span className="mr-status" role="status">
              {busy ? "Working…" : saved && current ? `Saved · version ${current.revision_number} · author: user` : current ? `Editing version ${current.revision_number}` : "Not saved yet"}
            </span>
            <span className="mr-spacer" />
            <EvidenceToggle className="mr-button mr-evidence" open={evidenceOpen} controls={evidenceId} onToggle={() => setEvidenceOpen(!evidenceOpen)} />
            <button type="button" className="mr-button" disabled={busy} onClick={() => void newDraft()} title="Start again from the run's current evidence">
              New draft
            </button>
            <button type="button" className="mr-button mr-button--primary" disabled={!title.trim() || !text.trim() || saved} onClick={() => void save()}>
              {current ? "Save report revision" : "Save manual report"}
            </button>
          </div>

          {reading ? (
            <article className="mr-paper">
              <ReportReadingView text={text} facts={evidence} />
            </article>
          ) : (
            <div className="mr-editor">
              <p className="mr-hint">
                Write freely. Numbers are kept as markers like <code>[[v:f_…]]</code> ({markers.length} here) and are filled from the
                evidence when the report is shown or exported, so they stay exact; delete a marker to drop its number.
              </p>
              <label className="manual-field">
                <span className="ws-visually-hidden">Report text</span>
                <textarea
                  aria-label="Report text"
                  maxLength={2_000_000}
                  rows={22}
                  value={text}
                  onChange={(event) => {
                    edited();
                    setText(event.target.value);
                  }}
                />
              </label>
              {markers.length > 0 && (
                <details className="mr-legend">
                  <summary>What each marker shows ({markers.length})</summary>
                  <dl>
                    {markers.map(({ marker, fact }) => (
                      <div key={marker} data-missing={!fact || undefined}>
                        <dt><code>{marker}</code></dt>
                        <dd>{fact ? `${factLabel(fact)}: ${factValue(fact)}` : "Names no single selected fact; it will be refused on save."}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              )}
            </div>
          )}

          {limitations.length > 0 && (
            <details className="mr-limits">
              <summary>Limits of this evidence ({limitations.length})</summary>
              <ul>{limitations.map((line, index) => <li key={index}>{line}</li>)}</ul>
            </details>
          )}

          {saved && current && (
            <section aria-label="Saved manual report" className="mr-saved">
              <span>Download version {current.revision_number}:</span>
              {EXPORTS.map(({ format, label }) => (
                <a key={format} className="mr-button" href={reportExportUrl(projectRoot, runId, current.id, format)} download>{label}</a>
              ))}
            </section>
          )}
        </fieldset>

        <ReportSources open={evidenceOpen} id={evidenceId}>
          <fieldset disabled={busy || !draft}>
            <h3>Scope</h3>
            <details>
              <summary>Source run</summary>
              <code>{runId}</code>
            </details>
            <AnalysisDisclosure projectRoot={projectRoot} runId={runId} />
            {current && <p>Saved evidence is fixed. Start a new draft to choose different evidence.</p>}
            <details>
              <summary>Computed evidence ({facts.length} selected)</summary>
              <div className="manual-facts">
                {evidence.map((fact) => (
                  <label key={fact.id}>
                    <input
                      type="checkbox"
                      disabled={current !== null}
                      checked={facts.includes(fact.id)}
                      onChange={(event) => {
                        edited();
                        setFacts((old) => choose(old, fact.id, event.target.checked));
                      }}
                    />
                    {factLabel(fact)}: {factValue(fact)}
                    <small title={`Exact value: ${String(fact.value)}`}> · {fact.source.run_id} · {fact.field}</small>
                  </label>
                ))}
              </div>
            </details>
            <details>
              <summary>Figures ({figures.length} selected)</summary>
              {figureEvidence.map((figure) => (
                <label key={figure.artifact_id}>
                  <input
                    type="checkbox"
                    disabled={current !== null}
                    checked={figures.includes(figure.artifact_id)}
                    onChange={(event) => {
                      edited();
                      setFigures((old) => choose(old, figure.artifact_id, event.target.checked));
                    }}
                  />
                  {figure.chart_type} · {figure.artifact_id}
                </label>
              ))}
            </details>
            <h3>Saved versions</h3>
            {history.length === 0 ? (
              <p>No saved manual reports yet.</p>
            ) : (
              history.map((report) => (
                <button type="button" key={report.id} disabled={busy} onClick={() => open(report)}>
                  {report.title} · version {report.revision_number} · {report.created_at}
                </button>
              ))
            )}
          </fieldset>
        </ReportSources>
      </div>
    </section>
  );
}
