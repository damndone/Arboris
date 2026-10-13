import {useAgentSurfaceOptional} from './AgentSurfaceContext';

/** Refresh persisted views when an Agent operation reaches completion. */
export function useCompletedOperation(): string | null {
  const operation = useAgentSurfaceOptional()?.activeOperation;
  return operation?.status === 'completed' ? operation.record_id : null;
}
