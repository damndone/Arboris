import "@testing-library/jest-dom/vitest";
import {render, screen} from "@testing-library/react";
import {expect, it} from "vitest";
import {EngineProvenanceNotice, parseEngineProvenance} from "./EngineProvenanceNotice";

const digest = "a".repeat(64);

it("shows the recorded native engine without mistaking its name for fallback", () => {
  render(<EngineProvenanceNotice modelId="iv_1" value={{requested: "fast", used: "arboris-engine",
    bit_identical_to_reference: false, build_identity_sha256: digest,
    build: {binary: "/private/bin"}, compiler: {path: "/private/compiler"}}}/>);
  expect(screen.getByText("Requested engine: fast")).toBeInTheDocument();
  expect(screen.getByRole("complementary", {name: "Estimation engine for iv_1"})).toHaveTextContent("Model: iv_1");
  expect(screen.getByText("Actual engine: arboris-engine")).toBeInTheDocument();
  expect(screen.getByText("Bit-identical to reference: no")).toBeInTheDocument();
  expect(screen.getByText(digest)).toBeInTheDocument();
  expect(screen.queryByText(/fallback/i)).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("/private/");
});

it("does not infer a fallback's bit identity or build hash", () => {
  render(<EngineProvenanceNotice modelId="iv_1" value={{requested: "fast", used: "reference", reason: "missing binary"}}/>);
  expect(screen.getByText("Actual engine: reference")).toBeInTheDocument();
  expect(screen.getByText("missing binary")).toBeInTheDocument();
  expect(screen.queryByText(/Bit-identical/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Build identity SHA256/)).not.toBeInTheDocument();
});

it("parses the unknown public boundary once and copies only bounded facts", () => {
  expect(parseEngineProvenance({requested: "fast", used: "reference", reason: "r".repeat(900),
    bit_identical_to_reference: "false", build_identity_sha256: "invalid", build: {compiler: "secret"}})).toEqual({
    requested: "fast", used: "reference", reason: "r".repeat(500) + "…",
  });
  expect(parseEngineProvenance(undefined)).toBeNull();
  expect(parseEngineProvenance({requested: "fast"})).toBeNull();
  expect(parseEngineProvenance([])).toBeNull();
});

it("adds no visible receipt to an absent/default provenance", () => {
  const {container} = render(<EngineProvenanceNotice modelId="iv_1" value={undefined}/>);
  expect(container).toBeEmptyDOMElement();
});
