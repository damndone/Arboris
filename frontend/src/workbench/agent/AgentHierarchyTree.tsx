import type { AgentHierarchyNode } from "./agentTypes";

export function AgentHierarchyTree({
  root,
  openNavigation,
}: {
  root: AgentHierarchyNode;
  openNavigation?: (ref: AgentHierarchyNode["ref"]) => boolean;
}) {
  return (
    <nav
      data-testid="agent-hierarchy-tree"
      aria-label="Main and Chain hierarchy"
      className="wb-agent-hierarchy"
    >
      <div className="wb-agent-hierarchy-title">Main / Chain hierarchy</div>
      <ul role="tree" aria-label="Main and Chain hierarchy" className="wb-agent-hierarchy-list">
        <HierarchyItem node={root} openNavigation={openNavigation} />
      </ul>
    </nav>
  );
}

function HierarchyItem({
  node,
  openNavigation,
}: {
  node: AgentHierarchyNode;
  openNavigation?: (ref: AgentHierarchyNode["ref"]) => boolean;
}) {
  const status = node.status ? ` · ${node.status}` : "";
  const accessibleName = `${node.ref.label}${status}`;
  return (
    <li
      role="treeitem"
      aria-label={accessibleName}
      aria-expanded={node.children.length > 0}
      className="wb-agent-hierarchy-item"
    >
      <button
        type="button"
        className="wb-agent-hierarchy-node"
        aria-label={`Open ${node.ref.label}`}
        disabled={!node.ref.available || !openNavigation}
        title={node.ref.available ? node.ref.label : node.ref.reason ?? "Unavailable"}
        onClick={() => {
          if (node.ref.available) openNavigation?.(node.ref);
        }}
      >
        <span className="wb-agent-hierarchy-marker" aria-hidden="true">
          {node.children.length > 0 ? "⌄" : "·"}
        </span>
        <span>{node.ref.label}</span>
        {node.status && <span className="wb-agent-hierarchy-status">{node.status}</span>}
      </button>
      {node.children.length > 0 && (
        <ul role="group" className="wb-agent-hierarchy-children">
          {node.children.map((child) => (
            <HierarchyItem
              key={`${child.ref.kind}:${child.ref.id}:${child.ref.relation}`}
              node={child}
              openNavigation={openNavigation}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
