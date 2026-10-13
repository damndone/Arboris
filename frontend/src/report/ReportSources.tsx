import {useId, useState, type ReactNode} from 'react';
import './report.css';

/** Keep immutable evidence beside the document without duplicating its state. */
export function ReportSources({children, defaultOpen = false}: {children: ReactNode; defaultOpen?: boolean}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return <aside className="report-sources" aria-label="Report sources">
    <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>Sources</button>
    <div id={id} hidden={!open} className="report-sources__body">{children}</div>
  </aside>;
}
