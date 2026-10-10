import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CrossRunTable } from "./CrossRunTable";
const fetchDetail=vi.hoisted(()=>vi.fn());
vi.mock("../../api",()=>({fetchRunDetail:fetchDetail}));
it("keeps the same model id distinct across saved runs",async()=>{
 fetchDetail.mockImplementation(async(_root:string,id:string)=>({model_results:[{model_id:"ols_1",model_type:"OLS",nobs:80,coefficients:{x:{estimate:id==='run_a'?1:2,std_error:.1,p_value:.0001,ci_lower:.8,ci_upper:2.2}}}]}));
 render(<CrossRunTable projectRoot="/project" runIds={['run_a','run_b']}/>);
 fireEvent.click(screen.getByText('Compare saved models side by side'));
 fireEvent.click(screen.getByLabelText('Include run run_a')); 
 fireEvent.click(screen.getByLabelText('Include run run_b'));
 expect(await screen.findByText(/OLS · a/)).toBeInTheDocument();
 expect(await screen.findByText(/OLS · b/)).toBeInTheDocument();
 expect(screen.getByText('source: run_a:ols_1.x')).toBeInTheDocument();
 expect(screen.getByText('source: run_b:ols_1.x')).toBeInTheDocument();
 expect(fetchDetail).toHaveBeenCalledWith('/project', 'run_a');
 expect(fetchDetail).toHaveBeenCalledWith('/project', 'run_b');
});

it("keeps group counts and difference tests scoped to their originating run", async () => {
 const model = {model_id:"m",model_type:"OLS",coefficients:{x:{estimate:1,std_error:.1,p_value:.02}}};
 fetchDetail.mockImplementation(async (_root:string,id:string) => ({model_results:id === 'groups' ? ['a','b'].map(key=>({...model,model_id:key,by_group:{column:"arm",key,n_groups:2,difference_tests:{status:"estimated",tests:[{label:"Within run",statistic:3,df_num:1,df_den:20,p_value:.03,distribution:"F"}]}}})):[model]}));
 render(<CrossRunTable projectRoot="/project" runIds={['groups','plain']}/>);
 fireEvent.click(screen.getByText('Compare saved models side by side'));
 fireEvent.click(screen.getByLabelText('Include run groups'));
 fireEvent.click(screen.getByLabelText('Include run plain'));
 expect(await screen.findByRole('note',{name:'Group evidence for groups'})).toHaveTextContent('2 of 2 groups');
 expect(screen.queryByText(/3 of 2 groups/)).toBeNull();
 expect(screen.getByRole('note',{name:'Group evidence for groups'})).toHaveTextContent('Within run');
});
