import { Trajectory } from "./Trajectory";
import { buildRepeatedMeasuresViewModel } from "./repeatedMeasuresViewModel";

export function PacketPanel({ result }: { result: unknown }) {
  const viewModel = buildRepeatedMeasuresViewModel(result);
  if (viewModel.kind === "rejected") {
    return <section aria-label="lmm-result-unavailable">Model result unavailable</section>;
  }
  if (viewModel.kind === "failed") {
    return (
      <section aria-label="linear-mixed-effects-result">
        <h2>Model fit failed</h2>
        {viewModel.terminalDiagnostics.map((diagnostic) => <p key={diagnostic}>{diagnostic}</p>)}
      </section>
    );
  }
  return (
    <section aria-label="linear-mixed-effects-result">
      <h2>Linear mixed-effects model result</h2>
      <dl>
        <dt>Primary coefficient</dt><dd>{viewModel.primaryCoefficient.label}</dd>
        <dt>Estimate</dt><dd>{viewModel.primaryCoefficient.estimate}</dd>
        <dt>Inference method</dt><dd>{viewModel.primaryCoefficient.inference_method}</dd>
        <dt>Server artifact ID</dt><dd>{viewModel.sourceMetadata.artifactId}</dd>
        <dt>Server artifact path</dt><dd>{viewModel.sourceMetadata.artifactPath}</dd>
        <dt>Artifact SHA-256</dt><dd>{viewModel.sourceMetadata.artifactSha256}</dd>
        <dt>Source contract</dt><dd>{viewModel.sourceMetadata.sourceContract}@{viewModel.sourceMetadata.sourceContractVersion}</dd>
        <dt>Source producer</dt><dd>{viewModel.sourceMetadata.sourceProducerVersion}</dd>
        <dt>Source packet SHA-256</dt><dd>{viewModel.sourceMetadata.sourcePacketDigest}</dd>
      </dl>
      {viewModel.diagnostics.map((diagnostic) => <p key={diagnostic.code}>{diagnostic.code}</p>)}
      {viewModel.trajectory === null
        ? <p>Group trajectories unavailable</p>
        : <Trajectory context={viewModel.trajectory} />}
    </section>
  );
}
