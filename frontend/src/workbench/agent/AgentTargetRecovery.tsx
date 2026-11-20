type Recovery = {
  message: string;
  source_run_id: string;
  requested_result_id: string | null;
  primary_result_id: string | null;
  steps: string[];
  options: { id: string; label: string; prompt: string }[];
};

function readRecovery(content: string): Recovery | null {
  try {
    const payload = JSON.parse(content);
    const value = payload?.output?.recovery;
    if (payload?.ok !== false || payload?.output?.status !== "needs_target_decision"
      || value?.schema !== "workbench.analysis-target-recovery.v1"
      || typeof value.message !== "string" || typeof value.source_run_id !== "string"
      || ![value.requested_result_id, value.primary_result_id].every((id) => id === null || typeof id === "string")
      || !Array.isArray(value.steps) || !value.steps.every((step: unknown) => typeof step === "string")
      || !Array.isArray(value.options) || !value.options.every((option: Recovery["options"][number]) =>
        option && typeof option.id === "string" && typeof option.label === "string" && typeof option.prompt === "string")) return null;
    return value;
  } catch {
    return null;
  }
}

export function AgentTargetRecovery({ content, onSelect, disabled }: {
  content: string;
  onSelect: (prompt: string) => void;
  disabled: boolean;
}) {
  const recovery = readRecovery(content);
  if (!recovery) return null;
  return (
    <section role="status" aria-label="Analysis target correction" className="wb-agent-target-recovery">
      <strong>Target conflict: correction options</strong>
      <p>{recovery.message}</p>
      <div>Source: {recovery.source_run_id}</div>
      <div>Requested: {recovery.requested_result_id ?? "Not selected"}</div>
      <div>Source primary: {recovery.primary_result_id ?? "Not declared"}</div>
      <ol>{recovery.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
      <p>The correction options are plans for review. They do not approve or execute a different analysis.</p>
      {recovery.options.map((option) => (
        <button type="button" key={option.id} disabled={disabled || option.prompt.includes("… [truncated]")}
          onClick={() => onSelect(option.prompt)}>{option.label}</button>
      ))}
    </section>
  );
}
