import { describe, expect, it } from "vitest";
import { readReportEvidence } from "../../report/reportEvidence";

describe("v1.8.9 candidate frontend evaluation status", () => {
  it("accepts a complete typed evidence projection", () => {
    const projection = readReportEvidence({
      projectionId: "projection:report:v1",
      consumerId: "report",
      consumerVersion: "v1",
      artifactRef: "artifact:classification:1",
      envelopeRef: "envelope:classification:1",
      envelopeDigest: "a".repeat(64),
      status: "available",
      executionStatus: "completed",
      availability: "available",
      completenessStatus: "complete",
      facts: [{ factId: "fact:accuracy", statisticId: "accuracy", value: 0.8 }],
      sections: [{ key: "metrics", label: "Metrics", status: "available" }],
    });

    expect(projection?.envelopeDigest).toBe("a".repeat(64));
    expect(projection?.facts[0]?.value).toBe(0.8);
  });

  it("rejects incomplete evidence instead of inventing a status", () => {
    expect(readReportEvidence({ projectionId: "projection:bad", facts: [] })).toBeNull();
  });
});

