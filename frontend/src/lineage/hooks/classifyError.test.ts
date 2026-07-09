import { describe, expect, it } from "vitest";
import { classifyError } from "./useGraphData";
import { ApiError } from "../../api";
import { UnsupportedGraphSchemaError } from "../api/graphAdapter";

describe("classifyError", () => {
  it("classifies a real fetch rejection as network", () => {
    expect(classifyError(new TypeError("Failed to fetch")).kind).toBe("network");
  });

  it("classifies an adapter TypeError (not a fetch) as adapter_error", () => {
    expect(
      classifyError(new TypeError("Cannot read properties of undefined")).kind,
    ).toBe("adapter_error");
  });

  it("classifies a RangeError as adapter_error", () => {
    expect(classifyError(new RangeError("Invalid array length")).kind).toBe(
      "adapter_error",
    );
  });

  it("keeps ApiError 404 as not_found", () => {
    expect(classifyError(new ApiError(404, "nope")).kind).toBe("not_found");
  });

  it("keeps ApiError 422 as corrupt", () => {
    expect(classifyError(new ApiError(422, "bad")).kind).toBe("corrupt");
  });

  it("keeps unsupported schema", () => {
    expect(classifyError(new UnsupportedGraphSchemaError(99)).kind).toBe(
      "unsupported_schema",
    );
  });
});
