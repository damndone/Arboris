# WO-A live Agent integration objective

Expose the already implemented, read-only LMM public-result explanation and
recovery-advice recipe through the existing Agent capability/tool contract.
The tool must consume only `PublicModelResult` / bounded diagnostics from one
real run, never raw filesystem paths or persistence capabilities, and must not
create or apply a proposal.  It must make the browser Agent panel useful for a
completed local LMM run while preserving the existing no-LLM and malformed-run
failure behaviour.
