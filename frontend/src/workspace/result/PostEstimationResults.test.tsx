import {render, screen} from '@testing-library/react';
import {it, expect} from 'vitest';
import {modelTests, PostEstimationResults} from './PostEstimationResults';
it('binds saved tests to both owner and model and keeps tiny p values nonzero', () => {
  const entry = {run_id:'test-owner', model_run_id:'owner', artifact_id:'wald', operation_id:'postestimation.wald', result:{model_id:'ols_1',p_value:1e-20,statistic:123.4}} as never;
  expect(modelTests([entry],'other','ols_1')).toHaveLength(0);
  expect(modelTests([entry],'owner','other')).toHaveLength(0);
  render(<PostEstimationResults entries={modelTests([entry],'owner','ols_1')}/>);
  expect(screen.getByText('< 0.001')).toBeVisible();
  expect(screen.queryByText('ols_1')).toBeNull();
});
