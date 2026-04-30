import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders workbench controls", () => {
  render(<App />);

  expect(screen.getByText("Local Econometrics Workbench")).toBeInTheDocument();
  expect(screen.getByLabelText("parent folder")).toBeInTheDocument();
  expect(screen.getByLabelText("project name")).toBeInTheDocument();
  expect(screen.getByLabelText("run mode")).toBeInTheDocument();
  expect(screen.getByLabelText("data file")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run workflow" })).toBeDisabled();
});
