# Workbench in the AI Era - Strategic Adversarial Review

> Status: consolidated, read-only strategic review
> Date: 2026-07-10
> Scope: Econometrics Workbench product strategy under increasingly capable general-purpose coding and analysis agents.
>
> This is the only record created by this review. It consolidates the former
> `task_plan.md`, `findings.md`, and `progress.md`; those files are removed.
> The market-validation proposal later in this document is retained as audit
> history, but is superseded by the internal-only TODO below because real user
> and market validation are not currently available.

## Consolidated Record

### What Was Done

- Read the current unified-graph roadmap, v1.6.8 live follow-ups, architecture-debt ledger, recent git history, and relevant frontend/backend code.
- Dispatched two independent, read-only agents: one built the strongest continuation case; the other assumed the product should stop or radically narrow.
- Ran a second adversarial round in which each agent had to concede, rebut, or make the other agent's claims measurable.
- Independently verified three high-impact code claims: source comparison is not wired to an action, no backend `/llm/chat` route exists, and `run_inputs.json` is an internal-run provenance record rather than an external review package.
- Checked official current materials for general-agent and data-science-IDE capability. No code, tests, releases, branches, or product behavior were changed.

### Facts Worth Carrying Forward

- v1.6.8 has a real non-visual substrate: project forest, immutable rerun provenance, node identity/hash validation, artifacts, and run events.
- The user-facing execution lifecycle is not yet one source of truth: genesis and rerun have divergent pending behavior, while the run rail still polls every 30 seconds.
- Generic data-aware AI and code execution are not differentiators. The differentiable hypothesis is evidence, comparison, and review discipline, but that hypothesis is unvalidated.
- The current graph, chat, compare, and report surfaces must not be mistaken for completed product value merely because their skeletons exist.

### Documentation Rule From Now On

- This document is frozen strategic context, not a living backlog.
- `docs/superpowers/followups/v1.6.8-followups.md` remains the only live implementation TODO list.
- `docs/superpowers/roadmap/architecture-debt.md` is a constraint/reference document, not a second task queue. When an architecture item is actually approved for work, create one precise task in the live follow-ups list instead of copying planning files into the repository root.

## Revised Internal TODO

> This list deliberately assumes no user testing, market test, or paid pilot is available. It is a low-regret internal development sequence, not a claim that the product-market question has been answered.

### P0 - Make Current Graph State Truthful

1. **Unify operation lifecycle.** Define one typed lifecycle for genesis, rerun-child, and future operations: `draft`, `validating`, `queued`, `running`, `succeeded`, `failed`, `blocked`, and `unknown`. Use one event/state path for canvas, drawer, and run rail. Remove the current “draft disappeared but run is not visible” gap.
2. **Close known correctness boundaries.** Fix `POST /runs` project-root validation, draft-execute response shape asymmetry, the 30-second rail refresh gap, error classification, and production dead RunHistory code. These are known product-truth defects, not feature bets.
3. **Freeze surface expansion until P0 is green.** Do not add a generic Ask AI, generic report, Agent Harness, drag-and-drop builder, or another graph view while operations can still have ambiguous visible state.

### P1 - Create Reusable Contracts, Not More Screens

4. **Extract a narrow operation/evidence contract.** Start with internal execution only: input/data identity, specification snapshot, operation target, terminal state, artifact references, and explicit omissions. Keep it UI-independent and versioned; do not call it an audit product yet.
5. **Make API boundaries harder to drift.** Add generated OpenAPI types or an equivalent checked client contract before adding new cross-layer operations. Extract only operation orchestration, events, and result aggregation out of `api.py`; do not start a broad rewrite.
6. **Make comparison real and narrow.** After P0/P1, implement selected-two-node/model comparison for same-family runs, with an explicit comparability result and parameter/artifact diff. Do not build a generic visual comparison canvas first.

### P2 - Add Intelligence Only Where It Is Constrained

7. **Node AI becomes a read-only explainer first.** It may summarize the selected operation and its warnings, but it cannot alter graph state, produce a hidden draft, or issue a rerun. Every suggested action must be an explicit, typed, user-confirmed operation.
8. **Reports remain deterministic exports.** Add citations only after comparison and evidence fields exist; report generation must render recorded facts rather than create a second AI-authored source of truth.

### Deferred Until a New Product Decision

- Generic Agent Harness and multi-step autonomous execution.
- Stata/R/MCP execution adapters.
- Graph-first home-screen expansion, drag-and-drop building, bottom-console ambitions, and broad report authoring.
- Large CSS migration, full `api.py` rewrite, and GLM-family refactor unless one is independently needed by an approved P0/P1 task.

### Definition of Done for This TODO

- Every item must be entered once, with owner and acceptance criteria, in `v1.6.8-followups.md` before implementation starts.
- When an item is completed, delete it from that live backlog and rely on git history; do not create a new progress, findings, or task-plan file.
- Strategic reviews may add a frozen document under `docs/superpowers/roadmap/`, but may not become a second active task list.

## Mandate

Question the premise that a graph-centric econometrics workbench is valuable when a user can ask an agent to perform an analysis directly or control established tools such as Stata. Do not defend the current roadmap by default. Search for the strongest reasons to continue, narrow, pivot, or stop.

## Evidence Rules

- Separate repository facts from hypotheses and market assumptions.
- Every important recommendation must state its counterargument and a falsifiable trigger.
- No code changes, release actions, or product claims based solely on aspirational roadmap text.
- A feature only counts as a moat if a capable general agent cannot cheaply reproduce it for the target customer without the Workbench's accumulated state and workflow.

## Baseline Facts

| Fact | Evidence | Strategic implication |
|---|---|---|
| v1.6.8 moves project creation, dataset selection, genesis draft chain, and first run into the project graph | unified-graph roadmap section 3; v1.6.8 follow-ups section 0 | The product has started to own analysis lifecycle state, not only a run form. |
| v1.6.9 currently names arbitrary comparison, node AI, and cited reporting as three deliveries | unified-graph roadmap section 3 | The current plan can still become a set of disconnected features unless unified around one job. |
| API and front-end containers are increasing in size, and typed contracts are manually mirrored | architecture-debt D1 and D6 | Additional surface area without boundary work increases feature cost and correctness risk. |
| Genesis and rerun still have inconsistent pending visibility and polling semantics | v1.6.8 follow-ups section 4.1 | A "graph as truth" product cannot tolerate ambiguous execution state. |

## Question and Answer Record

### Q0. What is the proposition being tested?

**Question:** Is Workbench still strategically meaningful when a capable coding agent can execute a statistical analysis from natural-language requirements?

**Initial answer:** It is not meaningful as a manual model-running UI or a generic analysis chatbot. It may be meaningful as an evidence, governance, and contestability system for conclusions that must survive review. This remains a hypothesis, not a conclusion.

### Q1. What does a general agent commoditize?

**Working answer:** Form filling, ad hoc code generation, first-pass model selection, ordinary plots, ordinary reports, and tool control. Any Workbench feature that only makes those actions prettier has weak defensibility.

### Q2. What could remain scarce?

**Working answer:** Durable provenance, stable data and variable semantics, controlled execution policy, versioned counterfactual comparison, review responsibility, and a conclusion package that another person can inspect without trusting the original agent or analyst.

### Q3. What must be disproved before continuing?

**Working answer:** That a narrow target user will accept friction and pay for this evidence layer; that the graph measurably improves analysis quality or review time; and that a general agent cannot reproduce the evidence package cheaply in the user's existing environment.

### Q4. Does the existing code contain a real substrate or only a visual bet?

**Question:** What already exists that a strategic pivot can reuse, and what makes the current implementation fragile?

**Answer from local evidence:** The code has a non-visual substrate: node ownership and hash validation, immutable rerun provenance, project forests, and a backend run-event stream. However, the user-facing execution lifecycle is not yet unified: the live backlog records separate genesis and rerun pending behavior and a 30-second run-history poll. The AI client is already structurally cheap to wire, which is an argument against treating a node chat panel as a moat. The reusable asset is the operation/evidence contract, not the current collection of graph surfaces.

### Q5. What is the clearest technical proof of the current strategic gap?

**Question:** Can the existing implementation already support a trustworthy agent loop, or does it reveal why one would fail today?

**Answer from local evidence:** It reveals both. The backend EventManager provides ordered per-run events and terminal signals, while the project run rail uses a fixed 30-second polling hook. The node AI client already ships a structured context packet and guardrails, but it consumes only a text response. Therefore the next strategic increment cannot merely enable `/llm/chat`; it must make an AI proposal, execution intent, run lifecycle, evidence references, and review outcome one typed, inspectable operation record. Otherwise an agent sees more context but the customer sees another opaque message.

### Q6. Does the external product landscape support a generic AI-analysis route?

**Question:** Are live data context and agentic execution still differentiated capabilities?

**Answer from official external materials:** No. OpenAI describes Codex as an agent that can work across files, tools, and repeatable workflows. Posit documents an AI data-science assistant with access to live R/Python session context, data frames, plots, and console activity; it also presents inspectable executable code, governed environments, and package reproducibility as part of the product. These sources do not prove Workbench has no market, but they disprove any strategy built on “our AI can see the data and run the analysis.” The remaining test is whether an evidence and review contract changes a buyer outcome that those environments do not already solve.

**Evidence limits:** This review did not establish customer willingness to pay, the prevalence of Stata MCP workflows, or a baseline review-time cost. Competitive capability evidence cannot substitute for a real buyer experiment.

## Independent Agent A - Continuation Case

**Assignment:** Build the strongest evidence-based case for continuing, but only with a narrow target user and an explicit wedge. Identify leading features, necessary architecture, operational metrics, counterarguments, and kill criteria. Record questions, answers, and evidence.

### Return 1 - Raw Q&A

**Premises**

- **Fact:** v1.6.8 places Launcher, project graph, genesis draft, and the first run in one lifecycle; v1.6.9 presently lists arbitrary comparison, node AI, and cited reporting separately.
- **Fact:** Runs persist content hashes, form input, rerun provenance, override hash, and DAG hash; rerun writes validate owner, node hash, forest key, and context fingerprint.
- **Fact:** The execution substrate is a single worker and slot, and the node ledger assumes one concurrent writer.
- **Fact:** Node AI submits a structured context packet but remains feature-gated; API, frontend API types, and the primary route container are growing, and there is no project registry/settings backend.
- **Assumption:** A target user will pay for reviewable causal conclusions rather than faster code generation. This requires a paid pilot.

**Q1. What has a general agent commoditized?**

**A:** Natural language to code, Stata/R/Python control, form filling, routine model suggestion, ordinary plots, and first-draft reports are assumed to be commoditized or close to it. Workbench must not compete to run a first regression first. Its only possible competition is whether a conclusion can still be independently reviewed after the analyst leaves, a client challenges it, or the model changes.

**Q2. Which narrow ICP might pay, and why not general data analysts?**

**A:** The strongest hypothesis is a 3-15 person economic-consulting or public-policy evaluation team that repeatedly delivers DID/event-study causal conclusions to a partner, client, or methods reviewer. They buy less rework around why a conclusion changed, which assumptions were accepted, and whether it can be reproduced. General data-analysis users generally need one-off insight and code; review accountability is friction rather than value.

**Q3. What is the only cumulative state or network effect?**

**A:** Not the graph. The candidate asset is an account-level causal-conclusion precedent library: data identity, variable semantics, specification variants, results, challenged assumptions, review decisions, and responsibility record. Current immutable rerun and node identity help, but no account-level compounding exists unless teams reuse precedents and reviewers treat the record as authoritative.

**Q4. What is the one 12-month wedge?**

**A:** A **contestable causal conclusion package** for one DID/event-study conclusion: `claim -> predefined challenge -> comparable rerun -> review decision -> deliverable evidence package`. The graph becomes evidence navigation, not a first-screen selling point; AI becomes a constrained challenger, not a chat entry; reporting becomes package export, not a writing feature.

**Q5. Which three leading capabilities belong inside that wedge?**

**A:**

1. **Specification-change attribution comparison.** Reviewers can identify whether a conclusion changed because of sample, variable, covariance, or estimator; target a 50% reduction in time to locate a material change. It has no advantage for one-off OLS or without a reviewer.
2. **Verifiable conclusion package.** Bundle data hash, specification, diagnostics, execution state, omissions, review decision, and citations; target independently replayable or explicitly non-replayable packages. It loses when a customer already has low-cost Stata/Quarto/Git audit discipline.
3. **Constrained AI red-team reviewer.** Use the evidence package to propose a finite set of challenges; user confirms before execution; results become supports, weakens, or uncovered. Track accepted high-value challenges and require AI-caused erroneous execution to remain zero. It should stop if Agent plus Git/Quarto produces an equally reviewable challenge record.

**Q6. How should v1.6.9 and v1.7 change, and what precedes them?**

**A:** Replace the three v1.6.9 surfaces with one conclusion-package MVP limited to DID/event-study, one claim template, a small challenge set, and one review decision. First unify pending/failed/visible execution state across genesis and rerun. Then define an UI-independent `Evidence/ClaimPacket v1`, which records executor and environment identity. Extract only execution orchestration, SSE, and result aggregation from the API behind contract tests. Pause generic Agent Harness, drag-and-drop, and broad reporting until real review adoption; codegen and replaceable executor adapters become prerequisites afterward.

**Q7. What would falsify the continuation case?**

**A:** A pre-registered 90-day pilot fails if, after 30 real conclusion packages from three target teams: fewer than two teams renew at a stated price; review time fails to fall 30% or evidence-missing/rework fails to fall 50%; more than half of projects keep specification, review, and decisions outside; a strong agent plus existing tools rebuilds equivalent packages in 80% of cases for at most 20% extra human cost; or a graph-as-truth production inconsistency cannot be removed with a unified execution contract within 30 days.

**Q8. What are the sharpest questions for the stop case?**

**A:**

1. Give a complete Agent + Stata + Git replacement that lets a non-author review, challenge, and trace responsibility in 15 minutes without tacit memory.
2. Does the stop case reject graph as a home screen or evidence relationships underneath? If the latter, name an alternative data model that preserves branches, shared inputs, and execution state.
3. Is the expected lack of payment caused by an absent review pain or by current graph-workbench positioning?
4. Can an agent cheaply replicate a team’s accumulated precedents, challenge outcomes, and waiver reasons? What measured threshold proves it?
5. Will the stop case retract if three teams meet pre-agreed review, rework, and renewal thresholds?

### Strongest Counterarguments and Response

- Agent-generated code, plots, and reports are commodity; the wedge only survives measured reduction in third-party review cost.
- The graph may be complexity; it must be behind the conclusion package as drill-down and lose its product-center status if it does not improve comparison speed.
- Single-worker execution, file-system projects, and big API boundaries mean this is a controlled team pilot, not an enterprise platform claim.
- An AI red team is noise unless every challenge is executable, comparable, confirmation-gated, and measured.

### Antifragility Mechanisms

- Better models produce more candidate specifications, while Workbench limits, compares, and reviews the experiment set.
- Rejected challenges, errors, and omissions enter the conclusion package and become future policy rules; no silent mutation.
- Non-graph users see only a claim, risk, and decision; the graph expands only for why.
- A new executor creates an explicit executor diff; old evidence remains immutable.

### Three Self-Deceptions to Avoid

1. Treating lineage code volume as a customer moat.
2. Treating recorded provenance as proof that review is faster or more trusted.
3. Using the v1.6.9 feature list to avoid testing a single paid wedge.

### One-Page Continuation Recommendation

Approve only a 90-day, three-team, 30-conclusion-package paid validation for DID/event-study contestable conclusion packages. v1.6.9 first unifies execution state and defines an Evidence/ClaimPacket contract; comparison, AI, and reporting are compressed into that loop. Defer Agent Harness, drag-and-drop graphs, and broad reports. Stop or reduce to a thin agent workflow if the pre-registered renewal, review-time, and rework thresholds fail.

### Return 2 - Cross-Examination of Agent B

**Q1. Accept the six-week, three-organization thin-shell test?**

**A:** Accept, but freeze product expansion before the test and revise gates. Before the six-week clock begins, secure written participation from three organizations, naming buyer, analyst, independent reviewer, and a real project. Each organization completes at least two real conclusion packages. Randomly give a non-author reviewer either `Agent + Stata/R/Python + Git package` or a thin Evidence Envelope from the same source materials. In 15 minutes, answer: data version, execution version, primary specification, material change from baseline, omissions/waivers, and responsible person. Continue only if the thin envelope is at least 30% faster and two of three organizations state explicit renewal or paid-pilot intent. Do not build adapters, graph, chat, or report in the test; allow manual normalization of external packages.

**Q2. Replies to Agent B's five questions.**

1. **Concede.** No signed pilot currently proves buyer, user, or rejecter. Require three written design-partner commitments with a budget owner, maker, reviewer, and real project.
2. **Needs validation.** Do not claim a graph improves blind review. Require no reduction in correctness and at least a 30% review-time improvement relative to the Git package.
3. **Concede.** A prompt-first non-graph path must retain state; require that it can answer the fixed review questions with complete envelope fields.
4. **Concede.** The current text-only node AI cannot trace, freeze, overturn, and learn from a wrong AI conclusion. Run an error exercise: find input, tool version, approval, affected conclusion, and disposition in 15 minutes.
5. **Concede.** Do not increase internal execution surface before one lifecycle contract covers genesis and rerun. Until then, use external thin-shell evidence collection.

**Q3. Pressure-test Agent plus existing tools as a one-day evidence-package substitute.**

**A:** For a DID claim such as “a subsidy raised employment by 3.2pp,” a one-day agent-generated Git package could include `claim.yaml`, `data.sha256`, a Git commit, Stata/R/Python command, lockfile, run log, machine-readable main-versus-robust diff, output, omissions, and Markdown approval. A non-author spends 2 minutes on claim/data hash, 3 on command/tool version, 4 on specification change, 3 on output/log, and 3 on omissions/approval. If reviewers consistently answer correctly, the Git path wins and Workbench has no moat.

The current repository lacks an external-execution import contract. Its run inputs represent internal form, upload hash, rerun, and DAG hash, not external commands, Git commits, approval, or claim fields. Its compare structure remains source-bound and its interface is not yet wired for general comparison.

**Q4. Which continuation claims or features must be removed or downgraded?**

- Remove any “industry-leading” claim; no market or blind-test evidence supports it.
- Remove the v1.6.9 AI red-team promise; current AI is only a gated text interface.
- Downgrade the DID/event-study ICP to a recruitment hypothesis.
- Downgrade the renewal claim to a pre-registered metric.
- Downgrade graph to a third randomized review arm, never the default experience during validation.

**Q5. What is the smallest, irreplaceable, measurable core contract?**

**A:** `Reviewable Evidence Envelope v0`: an immutable, addressable object that binds `claim`, data fingerprint, analysis definition/command, tool and environment identity, input/output artifact hashes, change from baseline, omissions/waivers, approval decision, and responsible person. It succeeds when a non-author reaches a pre-defined evidence-answer standard within 15 minutes, or it clearly declares itself non-reproducible/evidence-insufficient. Graph is presentation, chat is explanation, and report is rendering; none binds versions, omissions, and responsibility.

**Q6. What stop conditions and asset disposition are accepted?**

**A:** Stop product-line expansion if any holds: three organizations with real independent review responsibility cannot be recruited; after six weeks the envelope does not improve review efficiency by 30% or improve correctness/omission discovery; Agent plus existing tools passes equivalent 15-minute review in 80% of cases at no more than one day production cost; or fewer than two organizations accept it as a formal review record or pay to continue. Freeze the graph canvas, draft UI, Agent Harness, and internal runner expansion. Preserve run inputs, artifact hashes, environment snapshot, and node-context validation as a read-only evidence format/internal library; extract them only if the external thin shell is adopted, otherwise archive and stop maintaining them.

**Q7. Falsifiable objections to Agent B.**

1. “One-day equivalent package” must be measured by fixed independent-review correctness and time; if Git packages pass equally, Agent B wins.
2. An automatic external adapter cannot prove the wedge; manual normalized packages are sufficient for the test and should fail first if the value is absent.
3. A non-graph path does not prove graph has no value; add a third arm that renders the same envelope with a graph. Permanently abandon graph-first if it adds no measurable benefit.

**Revised continuation recommendation:** Freeze v1.6.9/v1.7 graph, AI, and report expansion. Pre-recruit three organizations with independent review responsibility, then run a six-week external-execution Evidence Envelope crossover. Build the minimal contract only if 15-minute review accuracy, review time, and renewal intent materially beat Agent plus existing tools; otherwise stop the product line and preserve lineage only as a read-only evidence format.

## Main Reviewer - Cross-Validation and Decision

### Verified Claims

| Claim | Direct verification | Result |
|---|---|---|
| Current comparison is not a general usable comparison workflow | `CompareWithSourceSection.tsx` renders a button with no handler and only gates on rerun provenance | Confirmed |
| Node AI is not a live Workbench backend capability | frontend posts to `/llm/chat`; repository search finds no backend route | Confirmed |
| Internal run provenance is not an external audit envelope | `run_inputs.json` contains internal form, upload hash, rerun, override, and DAG fields, not claim, external command, Git commit, approval, or executor identity | Confirmed |
| General AI data-science context is differentiated | Official Codex and Posit materials show agentic multi-tool work and live R/Python session context already exist | Rejected as differentiation hypothesis |
| A narrow buyer will pay for independent review | No local evidence or external buyer study in this review | Unproven - experiment required |
| A graph improves review | No controlled measurement exists | Unproven - make it a randomized optional view |

### CEO Decision

**Freeze the Unified Graph Workbench as a product expansion thesis. Do not abandon the evidence substrate.**

Replace the customer promise:

> Old: every operation happens on one graph.
>
> New: every consequential causal claim can be independently traced, challenged, compared, and approved without trusting the original analyst or agent.

The graph becomes an optional materialized evidence view. It is never the source of truth, never the default customer value proposition, and never a reason to add an operation. The source of truth becomes a UI-independent, append-only `Reviewable Evidence Envelope` / `EvidenceClaimPacket`.

### The One Allowed Bet

Build no new graph UI, chat UI, report UI, drag-and-drop builder, generic comparison, or Agent Harness until a controlled validation passes.

The smallest candidate contract is:

`Claim -> EvidenceRef -> Challenge -> Execution -> ReviewDecision`

Required fields: claim, data fingerprint, analysis command/specification, executor and environment identity, artifact hashes, baseline diff, omissions/waivers, terminal state, reviewer decision, and responsible identity. A graph renders relations from this contract; an AI may only create a pending typed Challenge; a report can only export cited fields. Neither may create facts or mutate an approved claim silently.

### Two-Gate Validation Plan

| Gate | Time and investment | Design | Continue only if |
|---|---|---|---|
| 0. Recruit | two weeks, no product build | Get three written design-partner commitments. Name budget owner, analyst, independent reviewer, real project, and current review workflow. | All three agree to use real work; otherwise freeze the product line. |
| 1. Cheap falsification | six weeks, manual normalized external packages only | Each organization supplies at least two real DID/event-study conclusion packages. A non-author reviewer receives either Agent plus Stata/R/Python plus Git/Quarto evidence or a manually assembled Envelope. No graph, adapter, chat, or report is built. | Envelope shows no loss of accuracy, at least 30% lower median review time, better omission discovery, and two of three organizations will use it as a formal review record or enter a paid pilot. |
| 2. Controlled product proof | 90 days, only Envelope MVP and lifecycle work | Within-team crossover over ten packages per team. Compare Agent control, Envelope without graph, and optional graph drill-down. Measure team-level outcomes rather than treating packages as independent samples. | At least two teams renew at stated price; 15-minute trace accuracy >=90% and >=20 points over control; review time improves >=30%; missing-evidence rework falls >=50%; >=70% of work remains in the contract; Agent control cannot produce reviewer-accepted equivalent packets in 80% of cases at <=20% extra human cost. |

### Immediate Engineering Discipline

1. Do not begin a broad API or UI rewrite before Gate 1. A refactor cannot create buyer pain.
2. If internal execution participates in Gate 2, first unify genesis and rerun into one typed lifecycle: submitted, pending, running, succeeded, failed, blocked, cancelled/unknown. The current backend event stream and frontend polling split are not adequate for a "truth" claim.
3. Define the Envelope schema outside all UI. It must support external execution before new Stata/R/MCP adapters are considered.
4. After Gate 1, extract only execution orchestration, event delivery, and result aggregation behind tested service contracts. Do not take on a full `api.py` split or OpenAPI migration until the wedge has survived customer evidence.
5. Treat the current hash, provenance, node-context validation, artifacts, and events as reusable libraries. Stop treating the canvas, draft route, or internal runner as the product boundary.

### What to Stop or Defer Now

- Stop the three-surface v1.6.9 plan: arbitrary graph comparison, generic node Ask AI, and AI-written cited report.
- Stop v1.7 Agent Harness, graph drag-and-drop, bottom-console ambitions, and graph-first information architecture investment.
- Do not delete working fallback paths during validation; retire placeholders only when their replacement contract is live.
- Defer external execution adapters and broad engine expansion; manual package normalization is the more honest test.
- Defer large cosmetic CSS work and broad refactors. They are not a response to product uncertainty.

### Antifragility Rules

- Better models produce more candidate analyses: the Envelope constrains and compares them rather than competing to generate them.
- A bad AI result becomes a typed Challenge, affected Claim, disposition, and future policy rule; never a vanished chat message.
- A user who rejects graphs still gets a reviewable envelope; graph use can be measured and removed without corrupting evidence.
- A new executor is an explicit adapter/version change; it creates an executor diff instead of overwriting old evidence.
- A failed pilot costs little because it uses external/manual packages; the reusable provenance components can become a read-only format or be archived without another UI rewrite.

### Kill Decision

Stop expansion immediately if recruitment fails, if the manual test fails its pre-registered quality/time/adoption threshold, or if strong-Agent control produces reviewer-accepted equivalent evidence at comparable cost. Preserve the existing provenance primitives as a read-only format only if an external evidence workflow adopts them; otherwise archive the product line rather than using prior engineering effort to justify more roadmap work.

## Independent Agent B - Stop/Pivot Case

**Assignment:** Assume the product should be stopped, radically narrowed, or converted into a thin agent workflow. Find the most damaging alternatives, hidden costs, false-moat risks, UX traps, and technical contradictions. State precisely what evidence would reverse that recommendation. Record questions, answers, and evidence.

### Return 1 - Raw Q&A

**Premises**

- **Fact:** The roadmap calls for editing, rerun, comparison, AI, and reporting in one lineage graph.
- **Fact:** v1.6.9 proposes arbitrary comparison, node AI, and cited reporting, with an Agent Harness later.
- **Fact:** The node-AI UI calls `/llm/chat`, while the local backend does not yet define that route.
- **Fact:** The current source-compare section is restricted to a rerun source and its visible button has no action binding; it is not a general comparison product.
- **Assumption:** A strong general agent can execute ordinary statistical work through Stata/R/Python or a code environment. The repository contains no market validation of this assumption.
- **Assumption:** Customers will pay for evidence, audit, or review is unproven.

**Q1. What has a general agent and existing tools already replaced?**

**A:** Natural-language clarification, variable mapping, model suggestions, code generation, Stata/R/Python execution, sensitivity analysis, plots, narrative reporting, and parameter sweeps are assumed to be largely substitutable. The local runner is primarily an orchestration layer over statsmodels and linearmodels, not a proprietary statistical engine. The only non-proven substitute gap is a cross-person evidence package that is precise and unambiguous, not a graph UI.

**Q2. When are graph, draft, and lineage only implementation complexity?**

**A:** For a single analyst, one-off research, small teams, or organizations with disciplined Git/Jupyter/Stata do-files, the graph is another history browser. A parameter edit becomes a form-state machine while the product pays for owner, hash, and context protocol. Lineage becomes customer value only when an independent reviewer must trace a conclusion to a data version, execution, and change, and cannot accept the existing script/repository record. Otherwise Merkle, forest dedupe, and canvas are implementation tax. Legacy-run omission already weakens the claim that the graph is the whole truth.

**Q3. Which roadmap parts are feature theater or false moats?**

**A:** The v1.6.9 trio of arbitrary comparison, node AI, and cited report can look like an AI workbench without sharing a buyer job. Enabling disabled placeholders does not create value. A deterministic HTML report already exists, so an AI cited report is just a second reporting path unless it shortens review or carries responsibility. Candidate dead surfaces include Ask AI, Generate report, an unbound source-compare button, canvas drag-and-drop, the bottom console, and manual review flags.

**Q4. Who will not pay?**

**A:** Likely non-buyers are individual researchers, students, independent consultants, mature R/Python/Stata teams, one-off business users, and internal analysis without independent review. This is a market hypothesis, not a proven customer fact.

**Q5. Which architecture debt makes AI/compare/report investment dangerous?**

**A:** api.py, api.ts, and the workbench container enlarge the route, type, and state surface. More damaging, genesis and rerun expose different pending lifecycles, while the run rail polls every 30 seconds. This undermines any product claim that the graph is a reliable live record.

**Q6. What should stop, defer, or retire?**

**A:** Stop graph-first AI, general graph comparison, cited graph report, Agent Harness, drag-and-drop builder, bottom console, and the promise that every operation belongs in a graph. Defer large API split, OpenAPI codegen, and GLM refactor until a thin pivot demonstrates demand. Retire unimplemented AI/report/compare surfaces and known production dead code.

**Q7. What is the minimum viable pivot and stop criterion?**

**A:** Move to an external-analysis evidence package: the Agent or Stata/R/Python executes; Workbench captures data fingerprint, script/tool transcript, environment lock, input/output artifacts, omissions, human approvals, and reviewable diffs. Prompt-first is the default; graph is an optional review visualization. Stop after six weeks if three organizations will not use real projects, if Agent plus existing repository/templates can produce an equivalent package in a day, or if independent review does not become at least 30% faster or reduce reproducibility errors.

**Q8. What are the sharpest questions for the continuation case?**

**A:**

1. Who is the paying buyer, daily user, and rejecter, with a signed pilot rather than a persona?
2. In a blind comparison against Agent plus Stata/R/Python plus Git artifacts, which review metric does the graph improve, and by how much?
3. If users reject the graph, how does prompt-first preserve evidence without becoming another UI?
4. After one wrong AI analysis, who can locate responsibility, freeze evidence, overturn the conclusion, and turn the incident into executable policy?
5. Why enlarge the product surface before execution state, API boundaries, and typed contracts are unified?

### Substitution Test

| Candidate moat | Can a strong agent plus existing tools reproduce it cheaply? | Agent B conclusion |
|---|---|---|
| Natural language to analysis | Yes, by assumption | Not a moat |
| Graph rerun and draft | Approximate with scripts, Git branches, parameter tables, and tool calls | Not a moat |
| Node comparison | Generate parameter and result diffs; review gain must be proved | Unproven |
| HTML or AI report | Yes; deterministic HTML already exists | Not a moat |
| Merkle lineage | Approximate for individuals; expensive only in audit-heavy review | Candidate only |
| Controlled execution and responsibility record | Harder only when adopted by an approval and retention workflow | Only wedge worth testing |

### Antifragility Failure Tests

- Better models destroy a manual-operation UI; a thin evidence product must sell model-independent preservation and review.
- An AI error must be attributable to input, tool, version, approval, and affected conclusion; this is not yet proven by the node-AI path.
- File-system project roots and localStorage recents do not justify an enterprise governance claim.
- The current project home is graph-first; no non-graph completion path has been validated.
- The Python runner is coupled to the current executor; Stata/R/MCP adapters could force a provenance and artifact contract redesign.

### What Would Change the Stop Recommendation?

- Three organizations with explicit review responsibility use or pay for a real evidence-package pilot.
- A controlled comparison shows lower review time, fewer omissions, or lower dispute cost versus Agent plus existing tools.
- A real audit, investment, or policy review demands immutable, addressable analysis evidence that Git/notebooks do not satisfy.
- Reviewers voluntarily use the graph to answer review questions rather than treating it as run history.
- External Stata/R/Python outputs can be ingested without rebuilding the full internal executor.

### One-Page Veto

Freeze the unified-graph v1.6.9/v1.7 expansion. Run only a six-week, three-organization thin-shell validation: preserve and compare evidence from external execution, with a non-graph reviewer path. Continue only after actual payment intent or measured review benefit. Otherwise stop the product line rather than rationalizing further investment as roadmap completion.

### Return 2 - Cross-Examination of Agent A

**Q1. Accept the 90-day, three-team, 30-package experiment?**

**A:** Accept with revision. Thirty packages inside three teams are not thirty independent observations, and the design must distinguish better review discipline from Workbench value. Pre-register a within-team crossover: each team completes ten real packages, randomly assigning each to ClaimPacket MVP or a strong-Agent plus Stata/R/Python plus Git/Quarto best-practice package. A non-author reviewer, without oral handoff, performs a 15-minute evidence trace. Challenge and rerun are a subsequent step. Evaluate the 15-minute trace accuracy, median review time, missing-evidence rework, and fixed-price renewal at team level.

**Q2. Replies to Agent A's five questions.**

**A:**

1. **Concede.** An Agent-plus-tool substitute must include a claim manifest, data hash, script commit, executor/environment version, output, diff, omission statement, and approval record. It succeeds only if a non-author can correctly identify conclusion, input, specification, most recent change, and responsible person in 15 minutes without tacit memory.
2. **Concede.** Reject graph as the home screen, not evidence relationships. The substitute model is an append-only UI-independent ClaimPacket: `Claim -> EvidenceRef -> Challenge -> Execution -> ReviewDecision`; a DAG may be a materialized view.
3. **Needs validation.** Payment may fail because review pain is absent or because graph-first positioning is wrong. Compare a thin non-graph path with graph drill-down in the same ICP and price.
4. **Concede but test.** An agent can copy historical text, but may not cheaply reproduce authority-recognized waivers, challenges, and decisions. At least 30% of later packages must actually cite prior precedent and the Agent control must fail to reproduce the record within 20% extra human cost.
5. **Concede.** Withdraw the stop recommendation if pre-registered team-level thresholds are met.

**Q3. Can Agent plus Stata/R/Python/Git support a 15-minute non-author review?**

**A:** It can support traceability: a standardized directory, README, do-file/notebook, commit, lockfile, data hash, output snapshot, and `make verify` can answer provenance questions. It does not automatically support contestability and governance: finite challenge taxonomy, executable comparison per challenge, explicit omission/non-replayable declarations, challenge-to-claim states, waiver/approval responsibility, and frozen-change semantics. Agent B accepts that the latter should be the ClaimPacket test.

**Q4. Which Stop Case claims are withdrawn or conditional?**

- Withdraw the demand to stop every v1.6.9 item; allow only a ClaimPacket MVP, not three independent surfaces.
- Make graph conditional: it can be evidence drill-down, but must be downgraded if it does not improve trace or comparison speed.
- Make AI conditional: allow a confirmation-gated, typed red-team challenger; forbid generic chat.
- Correct the architecture position: immediately unify execution terminal state and define a narrow ClaimPacket contract, but do not begin a broad rewrite.

**Q5. What is the only allowed core contract?**

**A:** `Evidence/ClaimPacket v1` with a claim, data identity, specification snapshot, executor/environment, terminal event, challenge/comparison links, omissions, review decision, and responsible identity. Graph only renders it; AI chat only proposes a pending Challenge; AI reports only export it and cannot invent facts.

**Q6. What evidence retracts the stop recommendation?**

**A:** Pre-register within two weeks, finish the state-unification gate within 30 days, then observe 90 days. All must hold: three teams each finish ten real packages; at least two renew at an agreed price; non-author 15-minute trace accuracy is at least 90% and at least 20 points above control; median review time falls at least 30%; missing-evidence rework falls at least 50%; at least 70% of packages complete specification, review, and decision in-system; strong-Agent control cannot produce reviewer-accepted equivalent packets in 80% of cases at 20% extra human cost; every terminal package has a terminal event or explicit unknown state.

**Q7. Falsifiable objections to Agent A's continuation case.**

1. A before-and-after result confuses process training with product value; the crossover control falsifies this objection.
2. Fifteen-minute traceability may merely prove a standardized manifest is useful; if Agent-plus-Git reaches the same accuracy and cost, the wedge fails.
3. A precedent library may remain story rather than compound value; it must be cited and trusted in later reviews, and not cheaply reconstructed by control.

**Revised stop-or-pivot recommendation:** Allow only a 90-day three-team, 30-package DID/event-study ClaimPacket trial with a strong-Agent control. Freeze generic graph, chat, report, and Agent Harness. First unify terminal state and create the UI-independent claim/evidence/challenge/review contract. If renewal, non-author trace, review-time, rework, and substitution thresholds do not all pass, reduce to an external-execution evidence shell; if that fails, stop.

## Cross-Examination Protocol

1. Compare each claimed moat against the ability of a capable agent plus existing Stata/R/Python workflows.
2. Separate individual-user convenience from organizational accountability.
3. Test whether a graph is a customer-visible advantage or merely implementation complexity.
4. Force each proposed feature to name a buyer, a failure mode, a measurable outcome, and a deletion criterion.
5. Prefer a narrow, observable bet over broad platform rhetoric.

## Antifragility Tests

- New models become better at analysis: Workbench should gain value by producing richer, more comparable experiments rather than lose its role to a chat window.
- An AI run is wrong: the graph, validation policy, and review record should make the defect easier to find and should improve future guardrails.
- A customer rejects graph complexity: the system should still offer a prompt-first path while retaining graph evidence in the background.
- A model family or integration becomes obsolete: execution adapters should be replaceable without invalidating prior evidence.
- A proposed feature fails adoption: its data contract and action record should be reusable by another workflow rather than becoming a stranded UI surface.
