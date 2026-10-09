import { useEffect, useRef, useState } from "react";
import { reportDraft, reportHistory, saveReport, reportExportUrl, type Draft, type Report } from "./manualApi";
import "./manual.css";
export function ManualReportPanel({ projectRoot, runId }: {
    projectRoot: string;
    runId: string;
}) {
    const [draft, setDraft] = useState<Draft | null>(null);
    const [history, setHistory] = useState<Report[]>([]);
    const [title, setTitle] = useState("");
    const [text, setText] = useState("");
    const [facts, setFacts] = useState<string[]>([]);
    const [figures, setFigures] = useState<string[]>([]);
    const [current, setCurrent] = useState<Report | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [saved, setSaved] = useState(false);
    const saveId = useRef(`mrpt_${crypto.randomUUID()}`);
    const pending = useRef(false);
    const edit = () => { setSaved(false); saveId.current = `mrpt_${crypto.randomUUID()}`; };
    function useDraft(d: Draft) { setDraft(d); setTitle(d.title); setText(d.text); setFacts(d.facts.map(f => f.id)); setFigures(d.figures.map(f => f.artifact_id)); setCurrent(null); edit(); }
    useEffect(() => { let active = true; setBusy(true); setError(""); Promise.all([reportDraft(projectRoot, runId), reportHistory(projectRoot, runId)]).then(([d, h]) => { if (active) {
        useDraft(d);
        setHistory(h.reports);
    } }).catch(e => active && setError(String(e))).finally(() => active && setBusy(false)); return () => { active = false; }; }, [projectRoot, runId]);
    function select(r: Report) { setCurrent(r); setTitle(r.title); setText(r.text); setFacts(r.facts.map(f => f.id)); setFigures(r.figures.map(f => f.artifact_id)); setSaved(true); saveId.current = `mrpt_${crypto.randomUUID()}`; }
    async function save() {
        if (!draft || pending.current)
            return;
        pending.current = true;
        setBusy(true);
        setError("");
        try {
            const result = await saveReport(projectRoot, runId, { id: saveId.current, title, text, source_fingerprint: current?.source_fingerprint ?? draft.source_fingerprint, fact_ids: facts, figure_ids: figures, ...(current ? { parent_report_id: current.id } : {}) });
            select(result.record);
            setHistory(old => [result.record, ...old.filter(r => r.id !== result.record.id)]);
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
        finally {
            pending.current = false;
            setBusy(false);
        }
    }
    const evidence = current?.facts ?? draft?.facts ?? [];
    const figureEvidence = current?.figures ?? draft?.figures ?? [];
    return <section className="manual-panel" aria-label="Manual report"><header><h2>Write a report</h2><button type="button" disabled={busy} onClick={async () => { setBusy(true); setError(''); try {
        useDraft(await reportDraft(projectRoot, runId));
    }
    catch (e) {
        setError(String(e));
    }
    finally {
        setBusy(false);
    } }}>New draft from current evidence</button></header><p>Write locally. Computed evidence stays read-only; each save creates a version.</p><small>Run {runId}</small>
    {error && <p role="alert">{error}</p>}{busy && <p role="status">Working…</p>}
    <fieldset disabled={busy || !draft}><label className="manual-field">Report title<input aria-label="Report title" maxLength={300} value={title} onChange={e => { edit(); setTitle(e.target.value); }}/></label><label className="manual-field">Report text<textarea aria-label="Report text" maxLength={2000000} rows={10} value={text} onChange={e => { edit(); setText(e.target.value); }}/></label>
    {current && <p>Saved evidence is fixed. Start a new draft to choose different evidence.</p>}<details><summary>Computed evidence ({facts.length} selected)</summary><div className="manual-facts">{evidence.map(f => <label key={f.id}><input type="checkbox" disabled={current !== null} checked={facts.includes(f.id)} onChange={e => { edit(); setFacts(old => e.target.checked ? [...old, f.id] : old.filter(id => id !== f.id)); }}/>{f.label}: {String(f.value)}<small> · {f.source.run_id} · {f.field}</small></label>)}</div></details>
    <details><summary>Figures ({figures.length} selected)</summary>{figureEvidence.map(f => <label key={f.artifact_id}><input type="checkbox" disabled={current !== null} checked={figures.includes(f.artifact_id)} onChange={e => { edit(); setFigures(old => e.target.checked ? [...old, f.artifact_id] : old.filter(id => id !== f.artifact_id)); }}/>{f.chart_type} · {f.artifact_id}</label>)}</details>
    {(current?.limitations ?? draft?.limitations ?? []).map((s, i) => <p key={i}>{s}</p>)}<button type="button" disabled={!title.trim() || !text.trim() || saved} onClick={() => void save()}>{current ? 'Save report revision' : 'Save manual report'}</button></fieldset>
    {saved && current && <section aria-label="Saved manual report"><p role="status">Saved · version {current.revision_number} · author: user</p><h3>{current.title}</h3><pre>{current.text}</pre><p>Exports contain the saved version and its computed evidence.</p>{['html', 'docx', 'tex', 'pdf-print'].map(format => <a key={format} href={reportExportUrl(projectRoot, runId, current.id, format)} download>Export {format === 'pdf-print' ? 'print-ready HTML' : format.toUpperCase()}</a>)}</section>}
    <h3>Manual report history</h3>{history.length === 0 ? <p>No saved manual reports yet.</p> : history.map(r => <button type="button" key={r.id} disabled={busy} onClick={() => select(r)}>{r.title} · version {r.revision_number} · {r.created_at}</button>)}
  </section>;
}
