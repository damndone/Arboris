import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  completePublicModelResult,
  failedPublicModelResult,
  unbalancedPublicModelResult,
} from "./__fixtures__/publicModelResults";
import { PacketPanel } from "./PacketPanel";

describe("PacketPanel", () => {
  it("presents trusted complete facts without recovery or execution controls", () => {
    render(<PacketPanel result={completePublicModelResult()} />);

    expect(screen.getByLabelText("linear-mixed-effects-result")).toHaveTextContent("treated × time");
    expect(screen.getByText("0.8")).toBeInTheDocument();
    expect(screen.getByLabelText("lmm-group-trajectory")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/确认|恢复|执行|rerun/i)).toBeNull();
  });

  it("shows server-projected artifact and source metadata without recomputing it", () => {
    render(<PacketPanel result={completePublicModelResult()} />);

    expect(screen.getByText("artifact-lmm-1")).toBeInTheDocument();
    expect(screen.getByText("artifacts/model_results/linear_mixed_effects_1.result.json")).toBeInTheDocument();
    expect(screen.getByText("linear_mixed_effects.result@1.0")).toBeInTheDocument();
    expect(screen.getByText("linear_mixed_effects@1.0")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
  });

  it("presents unbalanced time as an unavailable trajectory without inventing points", () => {
    render(<PacketPanel result={unbalancedPublicModelResult()} />);

    expect(screen.getByText("组别轨迹不可用")).toBeInTheDocument();
    expect(screen.queryByLabelText("lmm-group-trajectory")).toBeNull();
  });

  it("presents a failed terminal result without a success claim or trajectory", () => {
    render(<PacketPanel result={failedPublicModelResult()} />);

    expect(screen.getByText("模型拟合未完成")).toBeInTheDocument();
    expect(screen.getByText("LMM_CONVERGENCE_FAILED")).toBeInTheDocument();
    expect(screen.queryByLabelText("lmm-group-trajectory")).toBeNull();
    expect(screen.queryByText(/成功|complete/i)).toBeNull();
  });
});
