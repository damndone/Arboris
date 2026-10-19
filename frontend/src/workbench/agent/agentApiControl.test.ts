import { afterEach, expect, it, vi } from "vitest";
import { approveAgentPlan, continueAgentTurn, getAgentPlan, getAgentTurnState, patchAgentPlan, queueAgentTurnMessage, resumeAgentTurn, sendAgentTurn } from "./agentApi";

afterEach(() => vi.unstubAllGlobals());
it("sends exact plan versions, mode, and explicit turn actions to their own endpoints", async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response("{}", {headers:{"Content-Type":"application/json"}}));
  vi.stubGlobal("fetch",fetch);
  await sendAgentTurn("/project","s /1","question",undefined,undefined,"proposal_only","auto");
  await getAgentPlan("/project","s /1");
  await patchAgentPlan("/project","s /1",{version:7,question:"edited"});
  await approveAgentPlan("/project","s /1",7);
  await getAgentTurnState("/project","s /1");
  await continueAgentTurn("/project","s /1",{execution_mode:"ask",execution_policy:"proposal_only"});
  await resumeAgentTurn("/project","s /1","original-turn");
  await queueAgentTurnMessage("/project","s /1","steer","direction");
  await queueAgentTurnMessage("/project","s /1","follow_up","later");
  const calls=fetch.mock.calls as [string,RequestInit?][];
  expect(calls.map(([url]) => url.split("?")[0].split("s%20%2F1")[1])).toEqual(["/turns","/plan","/plan","/plan/approve","/turn-state","/continue","/resume","/steer","/follow_up"]);
  expect(JSON.parse(calls[0][1]!.body as string)).toEqual({question:"question",execution_policy:"proposal_only",execution_mode:"auto"});
  expect(JSON.parse(calls[2][1]!.body as string)).toEqual({version:7,question:"edited"});
  expect(JSON.parse(calls[3][1]!.body as string)).toEqual({version:7});
  expect(JSON.parse(calls[6][1]!.body as string)).toEqual({turn_id:"original-turn"});
  expect(JSON.parse(calls[8][1]!.body as string)).toEqual({text:"later"});
});
