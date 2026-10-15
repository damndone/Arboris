import {useRef, type ReactNode} from 'react';

/** Delay the graph's layout work until requested, then preserve its local state. */
export function DeferredMap({visible, children}: {visible: boolean; children: ReactNode}) {
  const visited = useRef(false);
  if (visible) visited.current = true;
  return <div className="ws-map__graph" hidden={!visible}>{visited.current ? children : null}</div>;
}
