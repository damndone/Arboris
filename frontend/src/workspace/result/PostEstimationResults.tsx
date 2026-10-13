import type {PostEstimationResult} from '../../api';
import {formatEstimate, formatPValue} from '../../format/numbers';

const technical = /(?:^|_)(?:id|sha256|fingerprint|schema|version)$|^model_type$/;
function valueText(key: string, value: unknown): string {
  if (value === null || value === undefined) return 'Not reported';
  if (typeof value === 'number') return /p_value$/.test(key) ? formatPValue(value) : formatEstimate(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.map(item => valueText(key, item)).join(', ');
  if (typeof value === 'object') return Object.entries(value).map(([field, item]) => `${field.replace(/_/g, ' ')}: ${valueText(field, item)}`).join('; ');
  return String(value);
}
export function modelTests(entries: PostEstimationResult[], runId: string, modelId: string) {
  return entries.filter(entry => entry.model_run_id === runId && entry.result.model_id === modelId);
}
export function PostEstimationResults({entries}: {entries: PostEstimationResult[]}) {
  if (entries.length === 0) return <div aria-label="Saved model tests"><p>No saved tests for this model yet.</p></div>;
  return (
    <div aria-label="Saved model tests">
      {entries.map((entry) => (
        <article key={`${entry.run_id}:${entry.artifact_id}`}>
          <h3>{entry.title ?? entry.operation_id.replace(/^postestimation\./, '').replace(/[._]/g, ' ')}</h3>
          <dl>
            {Object.entries(entry.result).filter(([key]) => !technical.test(key)).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replace(/_/g, ' ')}</dt>
                <dd>{valueText(key, value)}</dd>
              </div>
            ))}
          </dl>
          <details>
            <summary>Source</summary>
            <pre>{JSON.stringify(entry, null, 2)}</pre>
          </details>
        </article>
      ))}
    </div>
  );
}
