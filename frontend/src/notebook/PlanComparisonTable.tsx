import type { NotebookOptionRevision } from "./contracts";

export function PlanComparisonTable({ options }: { options: NotebookOptionRevision[] }) {
  return (
    <section className="nb-comparison" aria-label="Comparison basis">
      <p>Compare how each plan answers your question before choosing a Draft. Rationale is an Agent judgment; evidence references and assumptions remain available for review.</p>
      <p>Historical options retain their original evidence. This view does not certify that an earlier comparison was result-blind.</p>
      <div className="nb-comparison-scroll">
        <table aria-label="Analysis plan comparison">
          <thead><tr><th scope="col">Comparison basis</th>{options.map((option) => <th scope="col" key={option.option_id}>{option.option_id}</th>)}</tr></thead>
          <tbody>
            <tr><th scope="row">Question fit</th>{options.map((option) => <td key={option.option_id}>{option.rationale}</td>)}</tr>
            <tr><th scope="row">Data support</th>{options.map((option) => <td key={option.option_id}>
              {option.evidence_refs?.length ? <ul>{option.evidence_refs.map((ref) => <li key={ref.evidence_id}>
                <code title={`${ref.result_hash} · ${ref.source_refs.join(", ")}`}>{ref.evidence_id}</code>
              </li>)}</ul> : "No recorded comparison evidence"}
            </td>)}</tr>
            <tr><th scope="row">Assumptions</th>{options.map((option) => <td key={option.option_id}>
              {option.assumptions.length ? <ul>{option.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul> : "None recorded; not proof that none are required"}
            </td>)}</tr>
            <tr><th scope="row">Cost</th>{options.map((option) => <td key={option.option_id}>Not estimated</td>)}</tr>
            <tr><th scope="row">Domain practice</th>{options.map((option) => <td key={option.option_id}>Not independently established</td>)}</tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
