---
name: figure-quality-assurance
description: Check figure claims, panel alignment, text collision evidence and actual Arboris exports against their registered source artifacts; state unavailable checks explicitly.
---

# Figure and export evidence review

Modified from nature-figure at commit
f8797feed6405035e7d57f59cb8ba393c6a98802. See ../NOTICE.md and ../LICENSE.
Use Arboris's existing declared visualization and export operations. This skill
executes no scripts, accesses no external service and grants no export authority.

1. Record the core conclusion, evidence chain, intended figure type and each
   panel's distinct role before requesting a figure. Link every quantitative
   panel to its exact source result, data ownership, revision and uncertainty
   definition; do not invent values or mechanisms from visual appearance.
2. Check comparable panels against final rendered plot-area geometry, shared
   edges, dimensions, labels and gutters. Use available native alignment evidence
   and its declared tolerance; preserve reasoned intentional exceptions. A
   source-code layout or attractive screenshot does not prove final alignment.
3. Inspect text collision and clipping evidence for the exact final export at
   its final dimensions, including labels, legends and uncertainty annotations.
   Missing rendered geometry or a missing collision checker means NOT_AUDITABLE;
   do not claim an automated collision check passed merely by reading prose.
4. Verify actual export completion through the operation record and artifact
   registry, format, source revision and available file digest. A planned file,
   stale preview or requested export is not a completed export. Compare QA
   evidence with that same final artifact after any revision or regeneration.
5. Return a bounded checklist with source references and pass, discrepancy,
   NOT_AUDITABLE or AUTHOR_INPUT_NEEDED for each check. Report missing independent
   n, sample definitions or uncertainty through the statistical review boundary.
   Never equate successful export with a scientifically supported conclusion.
