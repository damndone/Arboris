import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetVariable, EgressView } from "./dataViewApi";

const api = {
  fetchEgress: vi.fn(),
  fetchEgressAudit: vi.fn(),
  replaceEgressPolicy: vi.fn(),
  patchColumnSensitivity: vi.fn(),
  saveMetadata: vi.fn(),
};

vi.mock("./dataViewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./dataViewApi")>()),
  fetchEgress: (...args: unknown[]) => api.fetchEgress(...args),
  fetchEgressAudit: (...args: unknown[]) => api.fetchEgressAudit(...args),
  replaceEgressPolicy: (...args: unknown[]) => api.replaceEgressPolicy(...args),
  patchColumnSensitivity: (...args: unknown[]) => api.patchColumnSensitivity(...args),
  saveMetadata: (...args: unknown[]) => api.saveMetadata(...args),
}));

import { SharingPanel } from "./SharingPanel";
import { VariableView } from "./VariableView";

const REMOTE_DEFAULT = ["workbench_state", "schema", "metadata", "aggregate", "model_result"];

function egressView(overrides: Partial<EgressView> = {}): EgressView {
  return {
    project_root: "/p",
    policy: { version: 1, providers: {}, columns: {} },
    policy_source: "default",
    content_classes: [...REMOTE_DEFAULT, "rows", "unclassified"],
    sensitivity_levels: ["public", "internal", "sensitive", "restricted"],
    defaults: { remote: REMOTE_DEFAULT, local: [...REMOTE_DEFAULT, "rows", "unclassified"] },
    active_provider: { provider_id: "deepseek", provider_name: "DeepSeek", locality: "remote", allowed_classes: REMOTE_DEFAULT },
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.fetchEgress.mockResolvedValue(egressView());
  api.fetchEgressAudit.mockResolvedValue([
    {
      at: "2026-09-26T10:00:00.000+00:00", provider_id: "deepseek", provider_host: "api.deepseek.com",
      provider_locality: "remote", model: "deepseek-chat", message_count: 4, withheld_count: 1,
      redacted_columns: ["phone"], payload_bytes: 900,
      decisions: [{ index: 3, role: "tool", tool_id: "show_dataset_rows", content_class: "rows", decision: "withheld" }],
    },
  ]);
});

describe("SharingPanel", () => {
  it("shows what the active provider may receive and what was withheld", async () => {
    render(<SharingPanel projectRoot="/p" />);
    const panel = await screen.findByTestId("sharing-panel");
    expect(within(panel).getByText("DeepSeek")).toBeTruthy();
    expect(screen.getByLabelText("Send Individual rows")).not.toBeChecked();
    expect(screen.getByLabelText("Send Model results")).toBeChecked();
    const audit = screen.getByTestId("sharing-audit");
    expect(within(audit).getByText("show_dataset_rows")).toBeTruthy();
    expect(within(audit).getByText("phone")).toBeTruthy();
  });

  it("saves a project override for the active provider and can return to the default", async () => {
    const allowed = [...REMOTE_DEFAULT, "rows"];
    api.replaceEgressPolicy.mockResolvedValueOnce(
      egressView({
        policy: { version: 1, providers: { deepseek: { allow: allowed } }, columns: {} },
        active_provider: { provider_id: "deepseek", provider_name: "DeepSeek", locality: "remote", allowed_classes: allowed },
      }),
    );
    render(<SharingPanel projectRoot="/p" />);
    fireEvent.click(await screen.findByLabelText("Send Individual rows"));
    fireEvent.click(screen.getByRole("button", { name: "Save for this project" }));
    await waitFor(() => expect(api.replaceEgressPolicy).toHaveBeenCalledTimes(1));
    const [, policy] = api.replaceEgressPolicy.mock.calls[0];
    expect(policy.providers.deepseek.allow).toEqual(allowed);
    expect(await screen.findByText(/this project's setting/)).toBeTruthy();

    api.replaceEgressPolicy.mockResolvedValueOnce(egressView());
    fireEvent.click(screen.getByRole("button", { name: /Use default/ }));
    await waitFor(() => expect(api.replaceEgressPolicy).toHaveBeenCalledTimes(2));
    expect(api.replaceEgressPolicy.mock.calls[1][1].providers).toEqual({});
  });
});

describe("VariableView sharing", () => {
  const variables: DatasetVariable[] = [
    {
      position: 1, name: "phone", type: "string", dtype: "object", missing: 0, declared_missing_matches: 0,
      unique: 2, variable_label: null, value_labels: {}, measurement_level: null, user_missing_values: [],
      sensitivity: "sensitive", sensitivity_source: "suggested", sensitivity_suggested: "sensitive",
    },
  ];

  it("changes a column's sharing at once, without a new run", async () => {
    api.patchColumnSensitivity.mockResolvedValue(
      egressView({ policy: { version: 1, providers: {}, columns: { phone: "public" } } }),
    );
    render(<VariableView projectRoot="/p" runId="r1" variables={variables} totalRows={2} onSaved={vi.fn()} />);
    const select = screen.getByLabelText("Sharing of phone") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(within(select).getByText("auto (sensitive)")).toBeTruthy();
    fireEvent.change(select, { target: { value: "public" } });
    await waitFor(() => expect(select.value).toBe("public"));
    expect(api.patchColumnSensitivity).toHaveBeenCalledWith("/p", { phone: "public" });
    expect(api.saveMetadata).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review changes (0)" })).toBeDisabled();
  });
});
