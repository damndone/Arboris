import type { KeyboardEvent } from "react";
import type { GraphViewNode } from "../api/graphViewTypes";
import type { TabState } from "../../workbench/state/tabsSchema";

export interface DetailDrawerTabsProps {
  tabs: TabState[];
  nodes: GraphViewNode[];
  activeTabId: string | null;
  onActive: (id: string) => void;
  onClose: (id: string) => void;
  lastEvictedTabId?: string | null;
}

function labelFor(tab: TabState, nodes: GraphViewNode[]): string {
  if (tab.kind === "report-review") return "Report review";
  return (
    nodes.find((node) => node.id === tab.id || node.nodeKey === tab.nodeKey)
      ?.title ?? tab.nodeKey
  );
}

export function DetailDrawerTabs({
  tabs,
  nodes,
  activeTabId,
  onActive,
  onClose,
  lastEvictedTabId,
}: DetailDrawerTabsProps) {
  if (tabs.length === 0) return null;

  const activeIndex = Math.max(
    0,
    tabs.findIndex((tab) => tab.id === activeTabId),
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (tabs.length === 0) return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex = (activeIndex + delta + tabs.length) % tabs.length;
    onActive(tabs[nextIndex].id);
  };

  return (
    <div className="detail-tabs detail-tabs--versions" data-testid="detail-drawer-tabs">
      <div
        className="detail-tabs__strip detail-tabs__strip--compact"
        role="tablist"
        aria-label="Open workspace panels"
        tabIndex={0}
        onKeyDown={onKeyDown}
      >
        {tabs.map((tab) => {
          const label = labelFor(tab, nodes);
          const isActive = tab.id === activeTabId;
          return (
            <span
              className="detail-tabs__item"
              data-active={isActive ? "true" : undefined}
              key={tab.id}
            >
              <button
                type="button"
                className="detail-tabs__tab"
                role="tab"
                aria-current={isActive ? "true" : undefined}
                title={label}
                onClick={() => onActive(tab.id)}
              >
                {label}
              </button>
              {tab.kind === "node" && (
                <button
                  type="button"
                  className="detail-tabs__close"
                  aria-label={`Close ${label} tab`}
                  onClick={() => onClose(tab.id)}
                >
                  x
                </button>
              )}
            </span>
          );
        })}
      </div>
      {lastEvictedTabId && (
        <div className="detail-tabs__notice" role="status">
          Oldest tab closed to keep 8 tabs.
        </div>
      )}
    </div>
  );
}
