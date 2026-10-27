import { useEffect, useRef, useState } from "react";
import type { AgentSurfaceContextValue } from "./AgentSurfaceContext";
import { agentTurnActive } from "./AgentRunControls";
import { applyMode } from "../../workspace/agent/AgentModeMenu";
import { confirmAgentRewind } from "./rewindConfirmation";

const COMMANDS = ["/plan", "/ask", "/auto", "/stop", "/undo"] as const;
const HELP = `Available commands: ${COMMANDS.join(", ")}.`;

export function useAgentSlashCommands(agent: AgentSurfaceContextValue | null, onShowPlan?: () => void) {
  const [feedback, setFeedback] = useState<{ text: string; error?: boolean } | null>(null);
  const currentSession = useRef(agent?.sessionId);
  currentSession.current = agent?.sessionId;
  const commandRevision = useRef(0);
  useEffect(() => { setFeedback(null); commandRevision.current += 1; }, [agent?.sessionId]);

  // Called only from a user's submit action, before ordinary send/queue logic.
  const handleCommand = (text: string): boolean => {
    const trimmed = text.trim();
    if (!agent || !trimmed.startsWith("/")) return false;
    const [command, ...arguments_] = trimmed.split(/\s+/);
    commandRevision.current += 1;
    const revision = commandRevision.current;
    const session = agent.sessionId;
    const report = (message: string, error = false) => {
      if (currentSession.current === session && commandRevision.current === revision) {
        setFeedback({ text: message, error });
      }
    };
    if (!COMMANDS.some(known => known === command)) {
      report(`Unknown command ${command}. ${HELP}`, true);
      return true;
    }
    if (arguments_.length) {
      report(`${command} does not take arguments. Submit it on its own. ${HELP}`, true);
      return true;
    }
    const active = agentTurnActive(agent);
    if (active && ["/ask", "/auto", "/undo"].includes(command)) {
      report(`Stop the current turn before using ${command}.`, true);
      return true;
    }
    const request = (action: () => Promise<void>, pending: string) => {
      agent.setPrompt("");
      report(pending);
      void action().catch(reason => report(reason instanceof Error ? reason.message : "Command request failed.", true));
    };
    if (command === "/plan") {
      if (!agent.plan || !agent.showPlan) {
        report("No analysis plan is available in this view. No plan was created.");
      } else {
        onShowPlan?.();
        agent.showPlan();
        agent.setPrompt("");
        report("Showing the current analysis plan.");
      }
    } else if (command === "/auto" || command === "/ask") {
      if (command === "/auto" ? !agent.setExecutionMode : !agent.setExecutionMode && !agent.setExecutionPolicy) {
        report(`${command === "/auto" ? "Auto" : "Review"} mode is not available in this view.`, true);
      } else {
        applyMode(agent, command === "/auto" ? "auto" : "review");
        agent.setPrompt("");
        report(command === "/auto"
          ? "Auto within approved plan selected. Approve a plan before execution; high-risk actions still require confirmation."
          : "Review every step selected. Each step waits for your approval.");
      }
    } else if (command === "/stop") {
      if (!active) report("There is no active turn to stop.");
      else request(agent.abortTurn, "Stop requested; waiting for the current turn to stop.");
    } else if (command === "/undo") {
      let entryId: string | undefined;
      for (let index = agent.messages.length - 1; index >= 0; index -= 1) {
        const message = agent.messages[index];
        if (message.role === "user" && !message.entry_id.startsWith("local-") && message.stop_reason !== "revised") {
          entryId = message.entry_id;
          break;
        }
      }
      if (!entryId || !agent.rewindTo) report("There is no saved user message available to undo in this view.");
      else if (confirmAgentRewind()) {
        const rewind = agent.rewindTo;
        const target = entryId;
        request(() => rewind(target), "Restore requested; waiting for the conversation and analysis head.");
      } else report("Undo cancelled. The conversation and analysis were kept.");
    }
    return true;
  };
  return { handleCommand, feedback };
}
