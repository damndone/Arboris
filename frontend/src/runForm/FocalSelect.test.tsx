import { render, screen, fireEvent } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import { FocalSelect } from "./FocalSelect";

it("lets the user mark a subset of x as focal", () => {
  const onChange = vi.fn();
  render(<FocalSelect xColumns={["education", "age"]} focal={[]} onChange={onChange} />);
  expect(screen.getByText(/Optional: choose focal explanatory variable/i)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("education"));
  expect(onChange).toHaveBeenCalledWith(["education"]);
});

it("removes a column when toggled off", () => {
  const onChange = vi.fn();
  render(
    <FocalSelect xColumns={["education", "age"]} focal={["education"]} onChange={onChange} />,
  );
  fireEvent.click(screen.getByLabelText("education"));
  expect(onChange).toHaveBeenCalledWith([]);
});

it("is hidden for IV/DID families (focal is structural)", () => {
  const { container } = render(
    <FocalSelect xColumns={["age"]} focal={[]} onChange={() => {}} family="iv" />,
  );
  expect(container).toBeEmptyDOMElement();
});
