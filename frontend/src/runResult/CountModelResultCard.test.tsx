import "@testing-library/jest-dom/vitest";
import {render,screen} from "@testing-library/react";
import {describe,expect,it} from "vitest";
import {CountModelResultCard} from "./CountModelResultCard";

describe("Dispersion inference",()=>{
  it("shows estimated dispersion, interval and boundary LR separately",()=>{
    render(<CountModelResultCard model={{model_id:"nb",dispersion:"mean",alpha_estimated:true,
      ancillary_parameters:[{name:"alpha",estimate:.7,std_error:.1,conf_low:.5,conf_high:.9,scale:"natural"}],
      overdispersion_test:{statistic:12.,df:1,p_value:.0002,distribution:"chibar2(01)"}}}/>);
    expect(screen.getByRole("heading",{name:"Estimated dispersion (NB2)"})).toBeInTheDocument();
    expect(screen.getByText(/boundary LR/i)).toBeInTheDocument();
    expect(screen.getByText(/chibar2\(01\)/)).toBeInTheDocument();
  });
  it("labels a fixed value as unestimated and omits dispersion tests",()=>{
    render(<CountModelResultCard model={{model_id:"glm",dispersion:"mean",alpha_estimated:false,alpha_fixed_value:.7}}/>);
    expect(screen.getByText(/not estimated/)).toBeInTheDocument();
    expect(screen.queryByText(/boundary LR/i)).not.toBeInTheDocument();
  });
  it("retains the owner's explicit reason when an ancillary interval is unavailable",()=>{
    render(<CountModelResultCard model={{model_id:"nb",dispersion:"mean",alpha_estimated:true,
      ancillary_parameters:[{name:"alpha",estimate:.7,std_error:.1,conf_low:.5,conf_high:null,scale:"natural"}],
      warnings:[{code:"NB_ANCILLARY_CI_NUMERIC_RANGE",message:"Natural-scale confidence limit exceeds the finite numeric range."}]}}/>);
    expect(screen.getByRole("alert")).toHaveTextContent("NB_ANCILLARY_CI_NUMERIC_RANGE");
    expect(screen.getByRole("alert")).toHaveTextContent("finite numeric range");
  });
});
