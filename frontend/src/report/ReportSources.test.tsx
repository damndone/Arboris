import {fireEvent, render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ReportSources} from './ReportSources';
it('preserves source selections while the sidebar is closed and reopened', () => {
  render(<ReportSources><label>Include evidence<input type="checkbox" defaultChecked/></label></ReportSources>);
  expect(screen.getByLabelText('Include evidence')).not.toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Evidence'}));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'Evidence'}));
  fireEvent.click(screen.getByRole('button',{name:'Evidence'}));
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});
