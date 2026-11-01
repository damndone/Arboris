import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentAttachmentLink, AgentAuditLink } from "./AgentFileViewer";

const file = (name: string, kind: string, media_type: string) => ({ attachment_id: "a1", name, kind, media_type, bytes: 5, sha256: "s" }) as never;

afterEach(() => vi.unstubAllGlobals());

describe("files opened from the Agent column", () => {
  it("closes with the button, with Esc and with a click outside", () => {
    render(<AgentAttachmentLink attachment={file("plot.png", "image", "image/png")} url="/files/a1?project_root=p" />);
    const open = () => fireEvent.click(screen.getByRole("link"));
    open();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("agent-file-viewer")).toBeNull();
    open();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("agent-file-viewer")).toBeNull();
    open();
    fireEvent.click(screen.getByTestId("agent-file-viewer"));
    expect(screen.queryByTestId("agent-file-viewer")).toBeNull();
  });

  it("shows a Word file as the text the model reads and still offers the original", async () => {
    const fetched = vi.fn().mockResolvedValue(new Response("beta 0.33"));
    vi.stubGlobal("fetch", fetched);
    render(<AgentAttachmentLink attachment={file("draft.docx", "text", "application/x")} url="/files/a1?project_root=p" />);
    fireEvent.click(screen.getByRole("link"));
    await waitFor(() => expect(screen.getByText("beta 0.33")).toBeInTheDocument());
    expect(fetched.mock.calls[0][0]).toBe("/files/a1?project_root=p&view=text");
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/files/a1?project_root=p");
  });

  it("opens the audit over the page, without letting it run scripts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<h1>Agent audit</h1>")));
    render(<AgentAuditLink url="/audit" title="Agent audit">Audit</AgentAuditLink>);
    fireEvent.click(screen.getByRole("link", { name: "Agent audit" }));
    await waitFor(() => expect(screen.getByTestId("agent-file-viewer").querySelector("iframe")).toHaveAttribute("srcdoc", "<h1>Agent audit</h1>"));
    expect(screen.getByTestId("agent-file-viewer").querySelector("iframe")).toHaveAttribute("sandbox", "");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("agent-file-viewer")).toBeNull();
  });
});
