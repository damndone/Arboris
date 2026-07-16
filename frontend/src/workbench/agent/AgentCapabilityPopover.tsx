import { useState } from "react";
import type { AgentCapabilityCatalog, AgentCapabilityBoundaryItem } from "./agentTypes";

function BoundaryList({
  title,
  items,
  testId,
}: {
  title: string;
  items: Array<AgentCapabilityBoundaryItem | { operation_id: string; ui_description: string; risk_level?: string; confirmation_policy?: string; example_prompts?: string[] }>;
  testId: string;
}) {
  return (
    <section data-testid={testId} className="wb-agent-capability-section">
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="wb-agent-capability-empty">暂无已登记能力</p>
      ) : (
        <ul>
          {items.map((item) => {
            const operationId = "operation_id" in item ? item.operation_id : item.id;
            const description = "ui_description" in item ? item.ui_description : item.description;
            const examples = "example_prompts" in item && Array.isArray(item.example_prompts)
              ? item.example_prompts
              : [];
            return (
              <li key={operationId}>
                <div className="wb-agent-capability-title">
                  <span aria-hidden="true">{"operation_id" in item ? "✓" : "○"}</span>
                  <strong>{"operation_id" in item ? description : item.label}</strong>
                </div>
                <div className="wb-agent-capability-description">{description}</div>
                {"operation_id" in item && (
                  <div className="wb-agent-capability-meta">
                    {item.risk_level} · confirmation: {item.confirmation_policy} · {operationId}
                  </div>
                )}
                {examples.length > 0 && (
                  <div className="wb-agent-capability-example">例：{examples[0]}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function AgentCapabilityPopover({
  catalog,
}: {
  catalog?: AgentCapabilityCatalog | null;
}) {
  const [open, setOpen] = useState(false);
  const hasCatalog = Boolean(
    catalog
      && Array.isArray(catalog.capabilities)
      && catalog.boundary
      && Array.isArray(catalog.boundary.advisory)
      && Array.isArray(catalog.boundary.unsupported),
  );
  const capabilities = Array.isArray(catalog?.capabilities) ? catalog.capabilities : [];
  const advisory = Array.isArray(catalog?.boundary?.advisory) ? catalog.boundary.advisory : [];
  const unsupported = Array.isArray(catalog?.boundary?.unsupported)
    ? catalog.boundary.unsupported
    : [];
  const executable = capabilities.filter((item) => item.natural_language_enabled);

  return (
    <div className="wb-agent-capability-control">
      <button
        type="button"
        className="wb-agent-capability-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="agent-capability-trigger"
        onClick={() => setOpen((value) => !value)}
      >
        Capabilities
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Agent capabilities"
          data-testid="agent-capability-popover"
          className="wb-agent-capability-popover"
        >
          {!hasCatalog ? (
            <div className="wb-agent-capability-unavailable">Capabilities unavailable</div>
          ) : (
            <>
              <BoundaryList title="当前可以执行" items={executable} testId="agent-capability-executable" />
              <BoundaryList title="可以询问，但不能直接执行" items={advisory} testId="agent-capability-advisory" />
              <BoundaryList title="暂不支持" items={unsupported} testId="agent-capability-unsupported" />
            </>
          )}
        </div>
      )}
    </div>
  );
}
