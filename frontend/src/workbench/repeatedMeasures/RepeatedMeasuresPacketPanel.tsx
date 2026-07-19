import {
  buildRepeatedMeasuresViewModel,
  type ComparisonFactLayers,
  type RepeatedMeasuresRecoveryProposal,
} from "./repeatedMeasuresViewModel";
import { TrajectoryFigure } from "./TrajectoryFigure";

export type RepeatedMeasuresRequestedState = "idle" | "pending" | "running";

type RepeatedMeasuresPacketPanelProps = {
  packet: unknown;
  requestedState?: RepeatedMeasuresRequestedState;
  confirmed?: boolean;
  onConfirm?: (proposal: RepeatedMeasuresRecoveryProposal) => void;
};

function formatServerFact(value: unknown): string {
  if (value === undefined) return "未提供";
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value) ?? "未提供";
}

function ServerFactLayers(props: { facts: ComparisonFactLayers }) {
  const rows: Array<[string, Record<string, unknown>]> = [
    ["样本与数据", props.facts.data],
    ["参数", props.facts.parameters],
    ["结果", props.facts.results],
    ["结论", props.facts.conclusion],
  ];
  return (
    <section aria-label="Repeated measures comparison facts">
      <h3>比较事实</h3>
      <dl>
        {rows.map(([label, fact]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd><code>{formatServerFact(fact)}</code></dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function LmmServerFacts(props: { facts: Record<string, unknown> }) {
  const rows: Array<[string, unknown]> = [
    ["模式结构版本", props.facts.schema_version],
    ["合同版本", props.facts.contract_version],
    ["估计器版本", props.facts.estimator_version],
    ["模型标识", props.facts.model_id],
    ["模型类型", props.facts.model_type],
    ["引擎", props.facts.engine],
    ["收敛", props.facts.converged],
    ["优化器", props.facts.optimizer],
    ["观测数", props.facts.nobs],
    ["组数", props.facts.n_groups],
    ["每组观测数", props.facts.observations_per_group],
    ["排除行数", props.facts.excluded_rows],
    ["排除计数", props.facts.exclusion_counts],
    ["固定效应公式", props.facts.fixed_effects_formula],
    ["随机效应设定", props.facts.random_effects_specification],
    ["参考组", props.facts.reference_group],
    ["比较组", props.facts.comparison_group],
    ["结果身份", props.facts.result_identity],
    ["主目标", props.facts.primary_target_id],
    ["推断方法", props.facts.inference_method],
    ["主结果系数", props.facts.coefficients],
    ["随机效应", props.facts.random_effects],
    ["服务端诊断", props.facts.diagnostics],
    ["服务端警告", props.facts.warnings],
    ["图形上下文", props.facts.figure_context],
  ];
  return (
    <section aria-label="Repeated measures result facts">
      <h3>服务端模型事实</h3>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd><code>{formatServerFact(value)}</code></dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function RepeatedMeasuresPacketPanel(props: RepeatedMeasuresPacketPanelProps) {
  const viewModel = buildRepeatedMeasuresViewModel(props.packet);

  if (viewModel.phase === "confirmation" && !props.confirmed) {
    return (
      <section aria-label="Repeated measures proposal">
        <h2>需要确认</h2>
        <p>建议将随机斜率设为 false；确认前不会进入执行态。</p>
        <dl>
          <dt>操作</dt><dd>{viewModel.proposal!.operation_id}</dd>
          <dt>变更</dt><dd>random_slope: false</dd>
        </dl>
        <button type="button" onClick={() => props.onConfirm?.(viewModel.proposal!)}>
          确认恢复方案
        </button>
      </section>
    );
  }

  if (viewModel.phase === "confirmation" && props.confirmed) {
    if (props.requestedState === "pending") {
      return <section aria-label="Repeated measures status"><h2>等待执行</h2></section>;
    }
    if (props.requestedState === "running") {
      return <section aria-label="Repeated measures status"><h2>运行中</h2></section>;
    }
    return <section aria-label="Repeated measures status"><h2>已确认，等待服务端状态</h2></section>;
  }

  if (viewModel.phase === "compare") {
    const comparison = viewModel.comparison!;
    if (comparison.status === "complete") {
      return (
        <section aria-label="Repeated measures comparison">
          <h2>子运行比较</h2>
          <dl>
            {comparison.comparison_scope !== null && <><dt>范围</dt><dd>{comparison.comparison_scope}</dd></>}
            <dt>结果</dt><dd>{comparison.result_id}</dd>
            <dt>来源运行</dt><dd>{comparison.source_run_id}</dd>
            <dt>子运行</dt><dd>{comparison.child_run_id}</dd>
          </dl>
          {comparison.facts !== null && <ServerFactLayers facts={comparison.facts} />}
        </section>
      );
    }
    return (
      <section aria-label="Repeated measures comparison">
        <h2>比较受限</h2>
        <p>{comparison.message}</p>
        <p>原因：{comparison.reason_code}</p>
      </section>
    );
  }

  if (viewModel.phase === "success") {
    return (
      <section aria-label="Repeated measures result">
        <h2>运行成功</h2>
        <dl>
          <dt>结果</dt><dd>{viewModel.result!.result_id}</dd>
          <dt>估计值</dt><dd>{viewModel.result!.estimate}</dd>
          <dt>拟合方法</dt><dd>{viewModel.result!.fit_method}</dd>
        </dl>
        <LmmServerFacts facts={viewModel.result!.serverFacts} />
        {viewModel.result!.diagnostics.length > 0 && (
          <section aria-label="Repeated measures result warnings">
            <h3>模型警告</h3>
            <ul>
              {viewModel.result!.diagnostics.map((diagnostic) => (
                <li key={diagnostic.code}>{diagnostic.code}</li>
              ))}
            </ul>
          </section>
        )}
        {viewModel.result!.trajectory !== null && <TrajectoryFigure context={viewModel.result!.trajectory} />}
      </section>
    );
  }

  if (viewModel.phase === "diagnostic" && viewModel.diagnostics.length > 0) {
    return (
      <section aria-label="Repeated measures diagnostics">
        <h2>诊断</h2>
        <ul>
          {viewModel.diagnostics.map((diagnostic) => (
            <li key={diagnostic.code}>{diagnostic.code}: {diagnostic.message}</li>
          ))}
        </ul>
      </section>
    );
  }

  return <section aria-label="Repeated measures status"><h2>验证</h2></section>;
}
