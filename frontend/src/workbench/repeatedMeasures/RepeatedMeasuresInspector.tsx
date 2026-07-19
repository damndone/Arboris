import {
  ModelOptionsProvenance,
  type ModelOptionsBindingProvenance,
} from "./ModelOptionsProvenance";
import {
  RepeatedMeasuresPacketPanel,
  type RepeatedMeasuresRequestedState,
} from "./RepeatedMeasuresPacketPanel";
import type { RepeatedMeasuresRecoveryProposal } from "./repeatedMeasuresViewModel";

type RepeatedMeasuresInspectorProps = {
  packet: unknown;
  binding?: ModelOptionsBindingProvenance;
  requestedState?: RepeatedMeasuresRequestedState;
  confirmed?: boolean;
  onConfirm?: (proposal: RepeatedMeasuresRecoveryProposal) => void;
};

/** Packet-only inspector; provenance and model facts remain server supplied. */
export function RepeatedMeasuresInspector(props: RepeatedMeasuresInspectorProps) {
  return (
    <section aria-label="Repeated measures inspector">
      <h1>重复测量检查器</h1>
      {props.binding !== undefined && <ModelOptionsProvenance binding={props.binding} />}
      <RepeatedMeasuresPacketPanel
        packet={props.packet}
        requestedState={props.requestedState}
        confirmed={props.confirmed}
        onConfirm={props.onConfirm}
      />
    </section>
  );
}
