type WorkbenchImportMeta = ImportMeta & {
  env?: Record<string, string | boolean | undefined>;
};

function isEnabled(value: string | boolean | undefined): boolean {
  if (value === true) return true;
  if (typeof value !== "string") return false;
  return value === "1" || value.toLowerCase() === "true";
}

export function isAskAIEnabled(): boolean {
  const viteValue = (import.meta as WorkbenchImportMeta).env?.VITE_WORKBENCH_ASK_AI;
  const testValue =
    typeof process === "undefined"
      ? undefined
      : process.env.VITE_WORKBENCH_ASK_AI;
  const configuredValue = viteValue ?? testValue;
  // Ask AI is a product surface, not an opt-in experiment. Keep an explicit
  // false/0 switch for deployments that do not want to expose it.
  return configuredValue === undefined ? true : isEnabled(configuredValue);
}
