import { describe, it, expect } from "vitest";
import {
  ROLE_OF_EDGE_OP,
  ROLE_GROUP_ORDER,
  roleLabel,
  roleColorVar,
  roleAbbrev,
} from "./roles";

describe("roles", () => {
  it("maps edge ops to roles", () => {
    expect(ROLE_OF_EDGE_OP["enters_as_focal"]).toBe("focal");
    expect(ROLE_OF_EDGE_OP["offsets_as_exposure"]).toBe("exposure");
    expect(ROLE_OF_EDGE_OP["identifies_as_instruments"]).toBe("instruments");
    expect(ROLE_OF_EDGE_OP["configures_cluster"]).toBe("cluster");
  });
  it("orders groups canonically with treatment", () => {
    expect(ROLE_GROUP_ORDER).toEqual([
      "outcome", "focal", "treatment", "covariates",
      "instruments", "exposure", "unit", "time", "cluster",
    ]);
  });
  it("labels roles for humans", () => {
    expect(roleLabel("outcome")).toBe("Outcome Variable (Y)");
    expect(roleLabel("focal")).toBe("Focal Explanatory Variable (X)");
    expect(roleLabel("covariates")).toBe("Covariates (Z)");
  });
});

describe("role canvas helpers", () => {
  it("maps each role to a CSS colour var", () => {
    expect(roleColorVar("outcome")).toBe("var(--role-outcome)");
    expect(roleColorVar("focal")).toBe("var(--role-focal)");
    expect(roleColorVar("cluster")).toBe("var(--role-cluster)");
  });
  it("gives a short canvas abbreviation per role", () => {
    expect(roleAbbrev("outcome")).toBe("Y");
    expect(roleAbbrev("focal")).toBe("X");
    expect(roleAbbrev("treatment")).toBe("D");
    expect(roleAbbrev("covariates")).toBe("Z");
    expect(roleAbbrev("instruments")).toBe("IV");
    expect(roleAbbrev("explanatory_unspecified")).toBe("X?");
  });
});
