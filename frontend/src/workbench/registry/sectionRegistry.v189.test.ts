import { createElement } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  DataConsumerEvidenceSection,
  V189_DECLARATION_RENDERER_KEYS,
  sectionRegistry,
} from "./sectionRegistry";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";

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
    const entry = sectionRegistry.find((item) => item.id === "dataConsumerEvidence");

    expect(V189_DECLARATION_RENDERER_KEYS.dataConsumer).toBe("renderer:data-consumer-evidence.v1");
    expect(entry).toBeDefined();
    expect(entry?.order).toBe(29.25);
    expect(entry?.shouldRender(datasetNode())).toBe(true);
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
