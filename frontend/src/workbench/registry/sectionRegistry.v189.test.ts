import { createElement } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProjectRootProvider } from "../ProjectRootContext";
import {
  DataConsumerEvidenceSection,
  V189_DECLARATION_RENDERER_KEYS,
  sectionRegistry,
} from "./sectionRegistry";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";

const { resolvedContextMock, manifestMock, sourceContextMock } = vi.hoisted(() => ({
  resolvedContextMock: {
    current: {
      ok: true,
      context: {
        ownership: { owner_run_id: "run-1" },
        operation_target: { op_node_id: "node-1" },
      },
    },
  },
  manifestMock: vi.fn(),
  sourceContextMock: vi.fn(),
}));

vi.mock("../../lineage/detail/NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => resolvedContextMock.current,
}));

vi.mock("../../lineage/dataOperations", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../lineage/dataOperations")>();
  return {
    ...original,
    fetchDataOperationManifest: manifestMock,
    fetchDataColumnCastContext: sourceContextMock,
  };
});

vi.mock("../../lineage/detail/sections/DataOperationsSection", () => ({
  DataOperationsSection: (props: {
    sourceIdentity?: { source_artifact_id?: string };
  }) =>
    createElement("div", {
      "data-testid": "canonical-data-operations",
      "data-source-artifact": props.sourceIdentity?.source_artifact_id,
    }),
}));

const datasetNode = (projection?: unknown) => ({
  kind: "dataset_stage",
  stage: "clean",
  isDraft: false,
  trust: "ok",
  decisions: [],
  ...(projection === undefined ? {} : { dataConsumerProjection: projection }),
}) as unknown as GraphViewNode;

describe("Workbench declaration-derived evidence sections v1.8.9", () => {
  it("registers one stable data-consumer renderer key and section", () => {
    const entry = sectionRegistry.find((item) => item.id === "dataOperations");

    expect(V189_DECLARATION_RENDERER_KEYS.dataConsumer).toBe("renderer:data-consumer-evidence.v1");
    expect(entry).toBeDefined();
    expect(entry?.order).toBe(29.25);
    expect(entry?.shouldRender(datasetNode())).toBe(true);
  });

  it("mounts the canonical editor with the typed source identity", async () => {
    manifestMock.mockResolvedValue({ schema_version: "data-operation-manifest.v1", operations: [] });
    sourceContextMock.mockResolvedValue({ source_artifact_id: "artifact-1" });
    const entry = sectionRegistry.find((item) => item.id === "dataOperations");

    render(
      createElement(
        ProjectRootProvider,
        {
          projectRoot: "/tmp/project",
          children: entry ? createElement(entry.Component, { node: datasetNode() }) : null,
        },
      ),
    );

    await waitFor(() => expect(screen.getByTestId("canonical-data-operations")).toBeInTheDocument());
    expect(manifestMock).toHaveBeenCalledTimes(1);
    expect(sourceContextMock).toHaveBeenCalledWith("/tmp/project", "run-1", "node-1");
    expect(screen.getByTestId("canonical-data-operations")).toHaveAttribute(
      "data-source-artifact",
      "artifact-1",
    );
  });

  it("renders approved projection fields and fails closed for unknown shapes", () => {
    render(createElement(DataConsumerEvidenceSection, { node: datasetNode() }));
    expect(screen.getByTestId("data-consumer-evidence")).toHaveTextContent("UNAVAILABLE");
    cleanup();

    render(createElement(DataConsumerEvidenceSection, {
      node: datasetNode({ status: "available", evidence_grade: "A", lineage_ref: "lineage:1", secret: "do-not-render" }),
    }));
    expect(screen.getByTestId("data-consumer-evidence")).toHaveTextContent("available");
    expect(screen.getByTestId("data-consumer-evidence")).toHaveTextContent("lineage:1");
    expect(screen.getByTestId("data-consumer-evidence")).not.toHaveTextContent("do-not-render");
  });
});
