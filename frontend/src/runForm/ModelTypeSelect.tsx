import type { Capabilities, ModelTypeEntry } from "../capabilities/types";

type Props = {
  capabilities: Capabilities | null | undefined;
  value: string;
  onChange: (value: string) => void;
};

const FALLBACK_MODELS: ModelTypeEntry[] = [
  { key: "auto", label: "Auto (infer from y)", group: "auto" },
];

const GROUP_ORDER = ["Linear", "Binary", "Count", "Panel", "GLM"] as const;

export function ModelTypeSelect({ capabilities, value, onChange }: Props) {
  const models = capabilities?.model_types?.length
    ? capabilities.model_types
    : FALLBACK_MODELS;
  const auto = models.filter((model) => model.group === "auto");
  const byGroup = new Map<string, ModelTypeEntry[]>();
  for (const model of models) {
    if (model.group === "auto") continue;
    const group = byGroup.get(model.group) ?? [];
    group.push(model);
    byGroup.set(model.group, group);
  }
  const groups = [
    ...GROUP_ORDER.filter((group) => byGroup.has(group)),
    ...Array.from(byGroup.keys()).filter((group) => !GROUP_ORDER.includes(group as typeof GROUP_ORDER[number])),
  ];

  return (
    <select
      aria-label="model type"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {auto.map((model) => (
        <option key={model.key} value={model.key} title={model.description}>
          {model.label}
        </option>
      ))}
      {groups.map((group) => (
        <optgroup key={group} label={group}>
          {byGroup.get(group)!.map((model) => (
            <option key={model.key} value={model.key} title={model.description}>
              {model.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
