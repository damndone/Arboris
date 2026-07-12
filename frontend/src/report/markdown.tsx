// v1.6.12 T3 (V5) — minimal deterministic markdown renderer, zero new deps.
//
// LLM answers/reports arrive as markdown; until now both surfaces rendered the
// raw text (`###`, `**` visible). This renders the common subset the models
// actually emit: #–#### headings, paragraphs, -/* bullets, 1. ordered lists,
// ``` fences, --- rules, and inline **bold** / *italic* / `code`.
//
// `renderTextSpan` is the seam for cite-chip integration: every plain-text
// leaf (including inside bold/italic) passes through it, so ReportView can
// swap [[c:ID]] markers for chips without a second parser pass.
import type { CSSProperties, ReactNode } from "react";

export type TextSpanRenderer = (text: string, key: string) => ReactNode;

const defaultSpan: TextSpanRenderer = (text, key) => (
  <span key={key}>{text}</span>
);

// ── inline ──────────────────────────────────────────────────────

const INLINE_TOKEN = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;

export function renderInlineMarkdown(
  text: string,
  keyPrefix: string,
  renderTextSpan: TextSpanRenderer = defaultSpan,
): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const match of text.matchAll(INLINE_TOKEN)) {
    const index = match.index ?? 0;
    if (index > last) {
      out.push(renderTextSpan(text.slice(last, index), `${keyPrefix}-t${i++}`));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      out.push(
        <code key={`${keyPrefix}-c${i++}`} style={{ fontSize: "0.92em" }}>
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      out.push(
        <strong key={`${keyPrefix}-b${i++}`}>
          {renderInlineMarkdown(token.slice(2, -2), `${keyPrefix}-b${i}`, renderTextSpan)}
        </strong>,
      );
    } else {
      out.push(
        <em key={`${keyPrefix}-e${i++}`}>
          {renderInlineMarkdown(token.slice(1, -1), `${keyPrefix}-e${i}`, renderTextSpan)}
        </em>,
      );
    }
    last = index + token.length;
  }
  if (last < text.length) {
    out.push(renderTextSpan(text.slice(last), `${keyPrefix}-t${i++}`));
  }
  return out;
}

// ── blocks ──────────────────────────────────────────────────────

const HEADING_SIZES: Record<number, CSSProperties> = {
  1: { fontSize: 17, fontWeight: 700, margin: "14px 0 6px" },
  2: { fontSize: 15, fontWeight: 700, margin: "12px 0 5px" },
  3: { fontSize: 13.5, fontWeight: 650, margin: "10px 0 4px" },
  4: { fontSize: 13, fontWeight: 650, margin: "8px 0 3px" },
};

export function renderMarkdown(
  text: string,
  renderTextSpan: TextSpanRenderer = defaultSpan,
): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let fence: string[] | null = null;
  let key = 0;

  const flushPara = () => {
    if (para.length === 0) return;
    const joined = para.join(" ");
    blocks.push(
      <p key={`p${key++}`} style={{ margin: "6px 0", lineHeight: 1.65 }}>
        {renderInlineMarkdown(joined, `p${key}`, renderTextSpan)}
      </p>,
    );
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    const items = list.items.map((item, idx) => (
      <li key={idx} style={{ margin: "2px 0", lineHeight: 1.6 }}>
        {renderInlineMarkdown(item, `l${key}-${idx}`, renderTextSpan)}
      </li>
    ));
    blocks.push(
      list.ordered ? (
        <ol key={`ol${key++}`} style={{ margin: "6px 0", paddingLeft: 22 }}>{items}</ol>
      ) : (
        <ul key={`ul${key++}`} style={{ margin: "6px 0", paddingLeft: 22 }}>{items}</ul>
      ),
    );
    list = null;
  };

  for (const line of lines) {
    if (fence !== null) {
      if (line.trim().startsWith("```")) {
        blocks.push(
          <pre
            key={`f${key++}`}
            style={{
              margin: "8px 0",
              padding: "8px 10px",
              borderRadius: 6,
              background: "var(--bg-card-2, rgba(0,0,0,0.05))",
              overflowX: "auto",
              fontSize: "0.92em",
            }}
          >
            {fence.join("\n")}
          </pre>,
        );
        fence = null;
      } else {
        fence.push(line);
      }
      continue;
    }
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      flushPara();
      flushList();
      fence = [];
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flushPara();
      flushList();
      const level = heading[1].length;
      blocks.push(
        <div key={`h${key++}`} role="heading" aria-level={level} style={HEADING_SIZES[level]}>
          {renderInlineMarkdown(heading[2], `h${key}`, renderTextSpan)}
        </div>,
      );
      continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      flushPara();
      flushList();
      blocks.push(
        <hr key={`r${key++}`} style={{ border: 0, borderTop: "1px solid var(--separator)", margin: "10px 0" }} />,
      );
      continue;
    }
    const bullet = /^[-*]\s+(.*)$/.exec(trimmed);
    const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
    if (bullet || ordered) {
      flushPara();
      const isOrdered = Boolean(ordered);
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { ordered: isOrdered, items: [] };
      }
      list.items.push((bullet ?? ordered)![1]);
      continue;
    }
    if (trimmed === "") {
      flushPara();
      flushList();
      continue;
    }
    if (list) {
      // continuation line of the previous list item
      list.items[list.items.length - 1] += ` ${trimmed}`;
      continue;
    }
    para.push(trimmed);
  }
  flushPara();
  flushList();
  if (fence !== null) {
    blocks.push(<pre key={`f${key++}`}>{(fence as string[]).join("\n")}</pre>);
  }
  return blocks;
}
