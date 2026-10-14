import { describe, expect, test } from "vitest";
import { agentMessageFixture as m } from "../../../apiFixtures";
import { buildTurns, chapterTitle, duration, messageTime } from "./turns";

const at = (seconds: number) => new Date(Date.UTC(2026, 9, 14, 9, 0, seconds)).toISOString();

describe("a conversation as turns", () => {
  test("steps, a withdrawn draft and the reply, with how long it took", () => {
    const reply = "The education coefficient is 2,564 (SE 70.91); experience adds 447 per year.";
    const turns = buildTurns([
      m({ entry_id: "u1", role: "user", content: "Explain the results", at: at(0) }),
      m({ entry_id: "t1", role: "tool", content: "{}", name: "inspect_model", at: at(3) }),
      m({ entry_id: "a1", role: "assistant", content: "Reading the model first.", stop_reason: "tool_calls", at: at(4) }),
      m({ entry_id: "d1", role: "assistant", content: "Education adds 2,600.", stop_reason: "revised", at: at(9) }),
      m({ entry_id: "a2", role: "assistant", content: reply, stop_reason: "tool_calls", at: at(11) }),
      m({ entry_id: "r1", role: "assistant", content: reply, stop_reason: "stop", at: at(12) }),
    ]);
    expect(turns).toHaveLength(1);
    const [turn] = turns;
    expect(turn.steps.map((step) => step.entry_id)).toEqual(["t1", "a1"]);
    expect(turn.drafts.map((draft) => draft.entry_id)).toEqual(["d1"]);
    expect(turn.responses.map((response) => response.entry_id)).toEqual(["r1"]);
    expect(turn.seconds).toBe(12);
  });

  test("a draft the rewrite kept word for word is not shown twice", () => {
    const text = "Both slopes are positive and precisely estimated in this sample of forty.";
    const [turn] = buildTurns([
      m({ entry_id: "u", role: "user", content: "q" }),
      m({ entry_id: "d", role: "assistant", content: text, stop_reason: "revised" }),
      m({ entry_id: "r", role: "assistant", content: text, stop_reason: "stop" }),
    ]);
    expect(turn.drafts).toEqual([]);
  });

  test("times, durations and chapter titles read as words", () => {
    const now = new Date(at(0));
    expect(messageTime(at(0), now)).toBe("09:00".replace("09", String(new Date(at(0)).getHours()).padStart(2, "0")));
    expect(duration(75)).toBe("1 min 15 s");
    expect(chapterTitle("## Results\nmore")).toBe("Results");
  });
});
