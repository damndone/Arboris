import { Handle, Position } from "reactflow";
import { roleAbbrev, roleColorVar, roleLabel, type Role } from "../roles";

export function VariableGroupNode({
  data,
}: {
  data: {
    label: string;
    gid: string;
    members: Array<{ id: string; title: string; summary: string | null; role?: Role }>;
    handleAxis?: "vertical" | "horizontal";
    selectedMemberId?: string | null;
    state?: "selected" | "focus" | "focus-upstream" | "related" | "dim";
    onSelectMember?: (nodeId: string) => void;
    onToggleGroup?: (groupId: string) => void;
  };
}) {
  const toggle = () => data.onToggleGroup?.(data.gid);
  const targetPosition = data.handleAxis === "vertical" ? Position.Top : Position.Left;
  const sourcePosition = data.handleAxis === "vertical" ? Position.Bottom : Position.Right;
  const handleStyle = {
    background: "transparent",
    border: 0,
    width: 1,
    height: 1,
    minWidth: 1,
    minHeight: 1,
  };
  return (
    <div
      className="ln-var-container ln-var-group-panel"
      data-testid="var-container"
      data-group-id={data.gid}
      data-state={data.state}
      aria-label={data.label}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <Handle
        type="target"
        position={targetPosition}
        isConnectable={false}
        style={handleStyle}
      />
      <div className="ln-var-group-panel__content" data-testid="var-group-panel">
        <button
          type="button"
          className="ln-var-container__header nodrag"
          data-testid="var-container-toggle"
          aria-label={`Collapse ${data.label}`}
          onClick={(event) => {
            event.stopPropagation();
            toggle();
          }}
        >
          {data.label}
        </button>
        <p className="ln-var-group-panel__browse">Scroll to browse all {data.members.length} items</p>
        <div
          className="ln-var-group-panel__grid nowheel nopan nokey nodrag"
          role="region"
          aria-label={`Browse ${data.label}`}
          tabIndex={0}
        >
          {data.members.map((member) => (
            <button
              key={member.id}
              type="button"
              className="ln-var-chip nodrag"
              data-testid={`var-chip-${member.id}`}
              data-selected={data.selectedMemberId === member.id ? "true" : undefined}
              aria-label={`Open ${member.title}`}
              onClick={(event) => {
                event.stopPropagation();
                data.onSelectMember?.(member.id);
              }}
            >
              {member.role && (
                <span
                  className="ln-var-chip__role"
                  title={roleLabel(member.role)}
                  style={{ ["--role-color" as string]: roleColorVar(member.role) }}
                >
                  {roleAbbrev(member.role)}
                </span>
              )}
              <span className="ln-var-chip__name">{member.title}</span>
              {member.summary && (
                <span className="ln-var-chip__meta">{member.summary}</span>
              )}
            </button>
          ))}
        </div>
      </div>
      <Handle
        type="source"
        position={sourcePosition}
        isConnectable={false}
        style={handleStyle}
      />
    </div>
  );
}
