import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, test} from 'vitest';
import {PostEstimationFields} from './PostEstimationResults';

const proof = Array.from({length: 400}, (_, index) => `8428454035135796445622476003710499923682${index}/62771017353866807638357894232076664161023554444640345128`);
const entry = {artifact_id: 'a', operation_id: 'iv.ar_confidence', run_id: 'r', model_run_id: 'r', workflow_step_id: 's', result: {
  contract: 'iv-ar.evidence.v1',
  model_sha256: '00079938540b9317161898f9e25e5662',
  covariance: 'robust',
  confidence_level: 0.95,
  anderson_rubin_95: {
    method: 'robust_hc0',
    critical_binary64_ratio: '6745789375439759/1125899906842624',
    lower: 0.2856424144107095,
    upper: 0.38490397973162516,
    global_certification: {status: 'certified', numerator_coefficient_bounds: proof},
  },
}} as never;

describe('post-estimation fields', () => {
  test('a person reads the finding, and the certificate stays one click away', () => {
    const {container} = render(<PostEstimationFields entry={entry} />);
    expect(screen.getByText('robust')).toBeInTheDocument();
    expect(screen.getByText('robust_hc0')).toBeInTheDocument();
    expect(screen.getByText('global certification').nextElementSibling).toHaveTextContent('certified');
    for (const hidden of ['iv-ar.evidence.v1', '00079938540b', '6745789375439759', '8428454035']) {
      expect(container.textContent).not.toContain(hidden);
    }
    const details = container.querySelector('details') as HTMLDetailsElement;
    expect(details.querySelector('pre')).toBeNull();
    details.open = true;
    fireEvent(details, new Event('toggle'));
    expect(details.querySelector('pre')?.textContent).toContain('8428454035');
  });
});
