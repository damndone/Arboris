/** Shared by transcript rewind and /undo; the existing server action retains evidence. */
export function confirmAgentRewind(): boolean {
  return window.confirm(
    "Restore the conversation and analysis head before this message on a new branch? " +
    "Original evidence is retained; external actions are not reversed.",
  );
}
