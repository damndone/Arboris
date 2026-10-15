import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {DeferredMap} from './DeferredMap';
it('mounts the graph only on first use and retains its state when hidden', () => {
 const {rerender}=render(<DeferredMap visible={false}><input aria-label="graph state" defaultValue="initial" /></DeferredMap>);
 expect(screen.queryByLabelText('graph state')).toBeNull();
 rerender(<DeferredMap visible><input aria-label="graph state" defaultValue="initial" /></DeferredMap>);
 const input=screen.getByLabelText('graph state') as HTMLInputElement;
 input.value='retained';
 rerender(<DeferredMap visible={false}><input aria-label="graph state" defaultValue="initial" /></DeferredMap>);
 expect(screen.getByLabelText('graph state')).toHaveValue('retained');
 expect(screen.getByLabelText('graph state')).not.toBeVisible();
 rerender(<DeferredMap visible><input aria-label="graph state" defaultValue="initial" /></DeferredMap>);
 expect(screen.getByLabelText('graph state')).toBe(input);
});
