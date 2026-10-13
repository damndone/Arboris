// v1.9.0 — writing a report by hand, without a language model. A draft starts
// from the run's computed evidence; the prose is the person's, the numbers
// stay read-only and cited. Every save is a new version linked to the one it
// revises, and exports carry that saved version with its evidence.

import { useEffect, useRef, useState } from "react";
import { AnalysisDisclosure } from "../report/AnalysisDisclosure";
import { ReportSources } from "../report/ReportSources";
import { reportDraft, reportExportUrl, reportHistory, saveReport, type Draft, type Report } from "./manualApi";
import { ReportReadingView, factLabel, factValue } from "./ReportEvidence";
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

  return (
    <section className="manual-panel" aria-label="Manual report">
      <header>
        <h2>Write a report</h2>
        <button type="button" disabled={busy} onClick={() => void newDraft()}>
          New draft from current evidence
        </button>
      </header>
      <p>Write locally. Computed evidence stays read-only; each save creates a version.</p>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">Working…</p>}

      <div className="report-document-layout">
        <fieldset className="report-document" disabled={busy || !draft}>
          <label className="manual-field">
            Report title
            <input
              aria-label="Report title"
              maxLength={300}
              value={title}
              onChange={(event) => {
                edited();
                setTitle(event.target.value);
              }}
            />
          </label>
          <div role="group" aria-label="Report display">
            <button type="button" aria-pressed={reading} onClick={() => setReading(true)}>Read</button>
            <button type="button" aria-pressed={!reading} onClick={() => setReading(false)}>Edit source</button>
          </div>
          {reading && <ReportReadingView text={text} facts={evidence} />}
          <label className="manual-field" hidden={reading}>
            Report text
            <textarea
              aria-label="Report text"
              maxLength={2_000_000}
              rows={10}
              value={text}
              onChange={(event) => {
                edited();
                setText(event.target.value);
              }}
            />
          </label>
          {limitations.map((line, index) => <p key={index}>{line}</p>)}
          <button type="button" disabled={!title.trim() || !text.trim() || saved} onClick={() => void save()}>
            {current ? "Save report revision" : "Save manual report"}
          </button>

          {saved && current && (
            <section aria-label="Saved manual report">
              <p role="status">Saved · version {current.revision_number} · author: user</p>
              <h3>{current.title}</h3>
              <ReportReadingView text={current.text} facts={current.facts} />
              <p>Exports contain the saved version and its computed evidence.</p>
              {EXPORTS.map(({ format, label }) => (
                <a key={format} href={reportExportUrl(projectRoot, runId, current.id, format)} download>{label}</a>
              ))}
            </section>
          )}
        </fieldset>

        <ReportSources>
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
            <h3>Manual report history</h3>
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
