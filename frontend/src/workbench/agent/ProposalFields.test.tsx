import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ProposalFields } from "./ProposalFields";
const mockCatalog = vi.hoisted(() => vi.fn());
vi.mock("../../manual/manualApi", () => ({ catalog: mockCatalog }));
describe("ProposalFields", () => {
  it("uses the manual declaration and validates revisions without another model call", async () => {
    mockCatalog.mockResolvedValue({ operations: [{ id: "data.recode", spec_schema: {type:"object", properties:{output:{type:"string",minLength:1}, limit:{type:"integer",minimum:1}},required:["output","limit"]} }] });
    const onChange=vi.fn(), onIssues=vi.fn();
    render(<ProposalFields projectRoot="/project" label="Changes" value={{steps:[{step_id:"recode",operation_id:"data.recode",spec:{output:"band",limit:0}}]}} onChange={onChange} onIssues={onIssues}/>);
    const limit=await screen.findByRole("spinbutton",{name:"Changes.steps[1].spec.limit"});
    await waitFor(()=>expect(onIssues.mock.lastCall?.[0].join(" ")).toMatch(/1/));
    fireEvent.change(limit,{target:{value:"2"}});
    expect(onChange).toHaveBeenCalledWith({steps:[{step_id:"recode",operation_id:"data.recode",spec:{output:"band",limit:2}}]});
    expect(mockCatalog).toHaveBeenCalledTimes(1);
  });
});
