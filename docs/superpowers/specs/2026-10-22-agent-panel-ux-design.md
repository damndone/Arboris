# Agent panel UX (v1.9.1)

Approved 2026-10-22. Reference: Claude Code's composer and model/permission pickers.

## Problems found

- The docked panel has a resize handle, but it sits at the viewport's left edge (x=0), not on the panel.
- Two controls set one decision: the `Mode` select (`ask` / `auto`) and the shield toggle
  (`proposal_only` / `auto_read_only`). Together they have three meaningful states.
- A running turn adds a delivery select and a send button; an unfinished turn adds a resume block.
- The plan card is a scroll box inside the panel; the stop-reason error is drawn over transcript text;
  the provider usage line takes a permanent row.
- Only the model can be chosen. Thinking effort is an environment variable; the context window cannot be set.

## Design

1. **Size.** The handle sits on the panel's left edge in every mode, 8px hit area, a hairline on hover.
   Double-click resets to 440px; minimum 320px; width persists. A narrow window squeezes the map first.
2. **One mode control.** A compact mode button in the composer bar opens three choices:
   *Review every step* (`ask` + `proposal_only`), *Run read-only analyses* (`ask` + `auto_read_only`),
   *Auto within approved plan* (`auto`). Shift+Tab in the composer cycles them. The footer note is removed.
3. **Running and recovery.** While a turn runs, the send button is Stop; a typed message is queued as a
   follow-up by default, with a small *Steer* toggle above the input. An unfinished turn shows one slim
   banner with *Resume*.
4. **Model picker.** The model name opens a popover: models, then for the current model *Thinking*
   (Off / Low / High / Max, shown for models that take a reasoning effort) and *Context*
   (128K / 1M, shown for models that support 1M). Both are saved on the provider's model record;
   requests read them. `WORKBENCH_REASONING_EFFORT` still overrides, so evaluation rounds are unchanged.
5. **Transcript.** Full-width text; the person's messages in a light right-aligned bubble; tool steps one
   collapsed line; the plan card collapsed to one line (title, status, step count) with small text actions
   and no inner scroll; errors as an inline callout in flow; usage moved into the context ring's tooltip.

## Not changed

Layout outside the Agent panel, the transcript data model, proposal card fields.

## Verification

Frontend tests for each change; backend tests that the per-model effort applies and the environment
variable wins; browser check at 14-inch and narrow widths, light and dark.
