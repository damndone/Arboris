export type ModelOptionsBindingProvenance = {
  owner_model_type: string;
  owner_model_id: string;
  producer_version: string;
  input_contract_version: string;
  normalized_options_hash: string;
};

export function ModelOptionsProvenance(props: {
  binding: ModelOptionsBindingProvenance;
}) {
  const rows: Array<[string, string]> = [
    ["Model type", props.binding.owner_model_type],
    ["Model id", props.binding.owner_model_id],
    ["Producer", props.binding.producer_version],
    ["Input contract", props.binding.input_contract_version],
    ["Options hash", props.binding.normalized_options_hash],
  ];

  return (
    <section aria-label="Model options provenance">
      <h2>参数来源</h2>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
