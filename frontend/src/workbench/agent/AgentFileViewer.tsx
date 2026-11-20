// A file or report opened from the Agent column, over the page: it closes with ×, Esc or a click outside,
// and the conversation stays where it was. Everything but an image shows as loaded text, so it also works
// where a browser would only download the file or refuses to frame the URL; Download gets the original.

import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { AgentMessage } from "./agentTypes";

type Attachment = NonNullable<AgentMessage["attachments"]>[number];
type Content = "image" | "text" | "page";

function AgentFileViewer({ title, url, downloadUrl, downloadName = title, content, onClose }: { title: string; url: string; downloadUrl: string; downloadName?: string; content: Content; onClose: () => void }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => {
      window.removeEventListener("keydown", onKey, { capture: true });
      opener?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    if (content === "image") return undefined;
    const request = new AbortController();
    fetch(url, { signal: request.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(String(response.status)))))
      .then(setText)
      .catch(() => { if (!request.signal.aborted) setFailed(true); });
    return () => request.abort();
  }, [content, url]);

  return createPortal(
    <div className="wb-file-viewer" role="dialog" aria-modal="true" aria-label={title} data-testid="agent-file-viewer"
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="wb-file-viewer__card">
        <header className="wb-file-viewer__head">
          <span className="wb-file-viewer__title" title={title}>{title}</span>
          <a href={downloadUrl} download={downloadName}>Download</a>
          <button ref={closeButton} type="button" aria-label="Close" onClick={onClose}>×</button>
        </header>
        {content === "image" && <div className="wb-file-viewer__image"><img src={url} alt={title} /></div>}
        {content === "page" && text !== null && !failed && <iframe className="wb-file-viewer__frame" srcDoc={text} title={title} sandbox="" />}
        {(content === "text" || text === null || failed) && content !== "image" && (
          <pre className="wb-file-viewer__text">{failed ? "This file could not be loaded." : text ?? "Loading…"}</pre>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** A modified click still opens the plain link, the way any link does. */
function opensHere(event: MouseEvent): boolean {
  if (event.metaKey || event.ctrlKey || event.shiftKey) return false;
  event.preventDefault();
  return true;
}

export function AgentAttachmentLink({ attachment, url }: { attachment: Attachment; url?: string }) {
  const [open, setOpen] = useState(false);
  const isImage = attachment.kind === "image";
  const content: Content = isImage ? "image" : "text";
  return (
    <>
      <a href={url} target="_blank" rel="noreferrer" title={attachment.name}
        className={isImage && url ? "wb-agent-attachment-image" : "wb-agent-attachment-file"}
        onClick={(event) => { if (url && opensHere(event)) setOpen(true); }}>
        {isImage && url ? <img src={url} alt={attachment.name} /> : attachment.name}
      </a>
      {open && url && (
        <AgentFileViewer title={attachment.name} content={content} downloadUrl={url} onClose={() => setOpen(false)}
          url={content === "text" ? `${url}&view=text` : url} />
      )}
    </>
  );
}

export function AgentAuditLink({ url, title, className, children }: { url: string; title: string; className?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <a href={url} target="_blank" rel="noreferrer" aria-label={title} title={title} className={className}
        onClick={(event) => { if (opensHere(event)) setOpen(true); }}>
        {children}
      </a>
      {open && <AgentFileViewer title="Agent audit" content="page" url={url} downloadUrl={url} downloadName="agent-audit.html" onClose={() => setOpen(false)} />}
    </>
  );
}
