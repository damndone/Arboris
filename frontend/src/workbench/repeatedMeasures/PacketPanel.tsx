import { Trajectory } from "./Trajectory";
import { buildRepeatedMeasuresViewModel } from "./repeatedMeasuresViewModel";

export function PacketPanel({ result }: { result: unknown }) {
  const viewModel = buildRepeatedMeasuresViewModel(result);
  if (viewModel.kind === "rejected") {
    return <section aria-label="lmm-result-unavailable">模型结果不可用</section>;
  }
  if (viewModel.kind === "failed") {
    return (
      <section aria-label="linear-mixed-effects-result">
        <h2>模型拟合未完成</h2>
        {viewModel.terminalDiagnostics.map((diagnostic) => <p key={diagnostic}>{diagnostic}</p>)}
      </section>
    );
  }
  return (
    <section aria-label="linear-mixed-effects-result">
      <h2>线性混合效应模型结果</h2>
      <dl>
        <dt>主要系数</dt><dd>{viewModel.primaryCoefficient.label}</dd>
        <dt>估计值</dt><dd>{viewModel.primaryCoefficient.estimate}</dd>
        <dt>推断方法</dt><dd>{viewModel.primaryCoefficient.inference_method}</dd>
        <dt>服务端工件 ID</dt><dd>{viewModel.sourceMetadata.artifactId}</dd>
        <dt>服务端工件路径</dt><dd>{viewModel.sourceMetadata.artifactPath}</dd>
        <dt>工件 SHA-256</dt><dd>{viewModel.sourceMetadata.artifactSha256}</dd>
        <dt>来源合同</dt><dd>{viewModel.sourceMetadata.sourceContract}@{viewModel.sourceMetadata.sourceContractVersion}</dd>
        <dt>来源生产者</dt><dd>{viewModel.sourceMetadata.sourceProducerVersion}</dd>
        <dt>来源数据包 SHA-256</dt><dd>{viewModel.sourceMetadata.sourcePacketDigest}</dd>
      </dl>
      {viewModel.diagnostics.map((diagnostic) => <p key={diagnostic.code}>{diagnostic.code}</p>)}
      {viewModel.trajectory === null
        ? <p>组别轨迹不可用</p>
        : <Trajectory context={viewModel.trajectory} />}
    </section>
  );
}
