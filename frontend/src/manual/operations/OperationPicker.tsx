// v1.9.0 — choosing an operation by hand. Groups follow the order a study
// moves in (prepare → explore → test → model → check → report); search reads
// titles, descriptions and ids. Each row says what the operation is for, or
// why it cannot run on the current target.

import { useId, useMemo, useState } from "react";
import { SearchIcon } from "../../workspace/icons";
import { dedicatedTargetReason } from "../dedicatedTarget";
import type { Operation, Target } from "../manualApi";

type Group = { key: string; label: string; order: number; items: Operation[] };

/** The catalog's own words; older servers without them fall back to the id. */
function groupOf(op: Operation): Omit<Group, "items"> {
  const label = op.group_label ?? op.category.replace(/_/g, " ");
  return { key: op.group ?? op.category, label: label[0].toUpperCase() + label.slice(1), order: op.group_order ?? 99 };
}

function blurbOf(op: Operation): string {
  return op.blurb ?? op.summary.split(/(?<=\.)\s/)[0];
}

export function whyNot(op: Operation, target: Target | undefined): string | undefined {
  return (
    dedicatedTargetReason(op, target) ??
    (op.availability.status === "unavailable" ? op.availability.message : undefined) ??
    (op.availability.status === "needs_target" && !target ? "Choose data or a model first." : undefined)
  );
}

function matches(op: Operation, query: string): boolean {
  if (!query) return true;
  const text = `${op.name} ${blurbOf(op)} ${op.id} ${groupOf(op).label}`.toLowerCase();
  return query.toLowerCase().split(/\s+/).every((word) => text.includes(word));
}

function groupsOf(operations: Operation[]): Group[] {
  const byKey = new Map<string, Group>();
  for (const op of operations) {
    const group = groupOf(op);
    if (!byKey.has(group.key)) byKey.set(group.key, { ...group, items: [] });
    byKey.get(group.key)!.items.push(op);
  }
  return [...byKey.values()].sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
}

function Row({ op, target, busy, onPick }: { op: Operation; target?: Target; busy: boolean; onPick: (op: Operation) => void }) {
  const id = useId();
  const reason = whyNot(op, target);
  return (
    <li>
      <button
        type="button"
        className="op-row"
        aria-labelledby={`${id}t`}
        aria-describedby={`${id}d`}
        disabled={busy || !!reason}
        onClick={() => onPick(op)}
      >
        <span id={`${id}t`} className="op-row__title">{op.name}</span>
        {!reason && op.execution.kind === "dedicated" && <span className="op-row__tag">Opens its own view</span>}
        <span id={`${id}d`} className="op-row__blurb" title={reason}>{reason ?? blurbOf(op)}</span>
      </button>
    </li>
  );
}

export function OperationPicker({
  operations,
  target,
  busy,
  initialSearch = "",
  onPick,
}: {
  operations: Operation[];
  target?: Target;
  busy: boolean;
  initialSearch?: string;
  onPick: (op: Operation) => void;
}) {
  const [query, setQuery] = useState(initialSearch);
  const [picked, setChosen] = useState<string | null>(null);
  const all = useMemo(() => groupsOf(operations), [operations]);
  const found = useMemo(() => groupsOf(operations.filter((op) => matches(op, query.trim()))), [operations, query]);
  // A search that empties the chosen group shows every group that matches.
  const chosen = picked && found.some((group) => group.key === picked) ? picked : null;
  const shown = chosen ? found.filter((group) => group.key === chosen) : found;
  const total = found.reduce((sum, group) => sum + group.items.length, 0);

  return (
    <div className="op-picker">
      <label className="op-search">
        <SearchIcon />
        <input
          aria-label="Find an operation"
          type="search"
          placeholder={`Search ${operations.length} operations`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <div className="op-picker__body">
        <nav className="op-groups" aria-label="Operation groups">
          <button type="button" className="op-groups__item" aria-pressed={chosen === null} onClick={() => setChosen(null)}>
            All<span>{total}</span>
          </button>
          {all.map((group) => {
            const count = found.find((g) => g.key === group.key)?.items.length ?? 0;
            return (
              <button
                key={group.key}
                type="button"
                className="op-groups__item"
                aria-pressed={chosen === group.key}
                disabled={count === 0}
                onClick={() => setChosen(chosen === group.key ? null : group.key)}
              >
                {group.label}<span>{count}</span>
              </button>
            );
          })}
        </nav>
        <div className="op-list" aria-live="polite">
          {total === 0 && <p className="op-empty">No operation matches “{query}”.</p>}
          {shown.map((group) => (
            <section key={group.key} aria-label={group.label}>
              {!chosen && <h3 className="op-list__heading">{group.label}</h3>}
              <ul>
                {group.items.map((op) => (
                  <Row key={op.id} op={op} target={target} busy={busy} onPick={onPick} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
