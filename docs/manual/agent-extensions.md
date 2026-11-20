# Tools and hooks

Open **Settings → Tools and hooks** in a project. Paste a manifest, choose
**Review manifest**, inspect its version, origin, schemas and endpoint, then
choose **Admit reviewed manifest**. Editing the JSON invalidates the review.
Admission replaces the catalog and re-enables its entries. Disable switches
operate on each tool or hook; admission itself does not execute anything.
Origins and versions are declarations reviewed by the person, not signatures
from the remote publisher. The digest pins the local adapter configuration.

```json
{
  "schema": "arboris.extensions.v1",
  "tools": [{
    "id": "literature",
    "version": "1",
    "origin": "https://example.invalid/adapter-source",
    "endpoint": "https://example.invalid/search",
    "input_schema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 200}}, "required": ["query"], "additionalProperties": false},
    "output_schema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"], "additionalProperties": false}
  }],
  "hooks": [{
    "id": "review-script-export",
    "version": "1",
    "origin": "local:research-policy",
    "event": "before_operation",
    "operation_ids": ["script.export"],
    "action": "deny",
    "reason": "Review the export policy before exporting scripts."
  }]
}
```

The URL above is illustrative. This version supports fixed HTTPS GET/JSON
adapters, not arbitrary executables or the complete MCP transport protocol.
Arguments travel in an `arguments` JSON query parameter, so the endpoint may
retain them in its access logs. There are no credentials, ambient proxies or
redirects. Request arguments are limited to 16 KB; the JSON result to 32 KB;
the catalog to 64 KB and 32 entries per slot. Schemas must be objects and may
not fetch references. Remote mutation tools need their own recovery contracts
and are not supported by this adapter.

**Allow query sharing to …** separately permits the `extension` content class
for `external:<tool-id>`. Inspect the arguments before approving each query;
this permission applies to those explicit arguments, not an automatic source
data upload. Discovery uses `inspect_extensions`, a read-only tool available
to Main and chain agents. Execution proposes `external.query` through the
same Analyze/workflow operation interface used manually. Both Ask and Auto
require a fresh human approval for the external operation. Catalog admission,
query approval and sharing permission cannot substitute for one another.
Remote model providers also need the `extension` sharing class to see external
metadata/results; that choice is separate from sharing with the endpoint.

The four hook events are `before_operation`, `after_operation`, `turn_end` and
`plan_approved`. They run in the shared operation/turn/approval lifecycle;
all file-export services and delivery entrances share an actor-independent
export boundary before writing or returning bytes. Use `operation_ids: ["export"]`
to deny every dataset, script, report, result-table, audit and artifact export.
Specific creation identities remain `export.dataset`, `script.export`,
`report.export`, `result_table.export` and `audit.export`; artifact delivery
uses `artifact.export`. Downloads are rechecked even for previously created
files, and client-rendered SVG downloads recheck the artifact boundary.
Nested report rendering uses the original project policy once, including
when figures are pinned to temporary storage. The boundary can only deny;
existing user approvals and sharing rules remain in force. Empty
`operation_ids` matches all events in the selected slot.
`record` is supported for all four; `deny` only before an operation. There are
no approval, shell or prompt actions. Hook receipts are bounded, atomically
published, and deduplicated by lifecycle identity and catalog digest.
Failures also receive an after-operation receipt. Observer failures are
recorded without changing the operation's committed outcome. An export denial
returns a visible policy refusal, not a generic server error.

External responses and project metadata remain untrusted tool data. They do
not register tools, approve plans, change sharing policy or supply native
statistical evidence. A persisted query result is reused on recovery. A crash
between a remote GET and local persistence can repeat that GET; remote
exactly-once delivery is not promised. Previously completed evidence remains
in the project when its adapter is disabled.

The provider-usage panel retains the provider's original usage object and
request/event IDs. Input, output, total, cache hit/miss and reasoning can be
compared with **Raw usage**. Reasoning is included in output, not added again.
Missing/inconsistent values remain unknown, partial sums are labelled, and
retries can consume tokens not reported by the provider. Costs remain
**unverified**; token snapshots are not a billing receipt.
