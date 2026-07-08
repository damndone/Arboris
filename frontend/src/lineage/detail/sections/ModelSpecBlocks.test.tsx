import { render, screen } from "@testing-library/react";
import { ModelSpecBlocks } from "./ModelSpecBlocks";

it("labels the RHS-only expression as model specification, not an estimated formula", () => {
  render(
    <ModelSpecBlocks
      spec={{
        outcome: "wage", focal: ["schooling"], covariates: ["age"],
        instruments: ["qob"], exposure: null, unit: null, time: null, cluster: null,
        se_type: "robust", estimator: "iv_2sls",
      }}
    />,
  );
  expect(screen.getByText("wage ~ schooling + age")).toBeInTheDocument();
  expect(screen.getByText("Model specification")).toBeInTheDocument();
  expect(screen.queryByText("Formula")).not.toBeInTheDocument();
  expect(screen.getByText(/Identification/)).toBeInTheDocument();
  expect(screen.queryByText(/qob/)).not.toBeNull();
});

it("shows explanatory-variables formula when focal empty", () => {
  render(
    <ModelSpecBlocks
      spec={{
        outcome: "y", focal: [], covariates: [], explanatory: ["a", "b"],
        instruments: [], exposure: null, unit: null, time: null, cluster: null,
        se_type: "HC1", estimator: "ols",
      }}
    />,
  );
  expect(screen.getByText("y ~ a + b")).toBeInTheDocument();
});

it("never folds instruments/exposure into the RHS formula", () => {
  render(
    <ModelSpecBlocks
      spec={{
        outcome: "y", focal: ["d"], covariates: [], instruments: ["z"],
        exposure: "pop", unit: null, time: null, cluster: "firm",
        se_type: "cluster", estimator: "poisson",
      }}
    />,
  );
  expect(screen.getByText("y ~ d")).toBeInTheDocument();
  expect(screen.getByText("Offset (exposure)")).toBeInTheDocument();
  expect(screen.getByText(/cluster: firm/)).toBeInTheDocument();
});
