import {useId, useState, type ReactNode} from 'react';
import './report.css';

/** Keep immutable evidence beside the document without duplicating its state.
 *  Uncontrolled, it carries its own toggle; controlled (open + onToggle), the
 *  host puts the toggle in its own toolbar (EvidenceToggle). */
export function ReportSources({children, defaultOpen = false, open: controlled, id: givenId}: {
  children: ReactNode; defaultOpen?: boolean; open?: boolean; id?: string;
}) {
  const [own, setOwn] = useState(defaultOpen);
  const ownId = useId();
  const id = givenId ?? ownId;
  const open = controlled ?? own;
  return <aside className="report-sources" aria-label="Report sources" data-open={open}>
    {controlled === undefined && <EvidenceToggle open={open} controls={id} onToggle={() => setOwn(value => !value)}/>}
    <div id={id} hidden={!open} className="report-sources__body">{children}</div>
  </aside>;
}

export function EvidenceToggle({open, controls, onToggle, className}: {open: boolean; controls: string; onToggle: () => void; className?: string}) {
  return <button type="button" className={className ?? 'report-sources__toggle'} aria-expanded={open} aria-controls={controls}
    title="The evidence, scope and saved versions behind this report" onClick={onToggle}>Evidence</button>;
}
