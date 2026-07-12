import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { renderMarkdown } from "./markdown";

function mount(text: string, renderTextSpan?: Parameters<typeof renderMarkdown>[1]) {
  return render(<div data-testid="md">{renderMarkdown(text, renderTextSpan)}</div>);
}

describe("renderMarkdown", () => {
  it("renders headings as heading-role elements, not literal hashes", () => {
    mount("## 方法\n\n正文段落。");
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("方法");
    expect(screen.getByTestId("md").textContent).not.toContain("##");
  });

  it("renders bold/italic/inline-code without marker characters", () => {
    mount("This is **bold** and *em* and `code`.");
    const md = screen.getByTestId("md");
    expect(md.querySelector("strong")).toHaveTextContent("bold");
    expect(md.querySelector("em")).toHaveTextContent("em");
    expect(md.querySelector("code")).toHaveTextContent("code");
    expect(md.textContent).not.toContain("**");
  });

  it("renders bullet and ordered lists", () => {
    mount("- first\n- second\n\n1. one\n2. two");
    const md = screen.getByTestId("md");
    expect(md.querySelectorAll("ul li")).toHaveLength(2);
    expect(md.querySelectorAll("ol li")).toHaveLength(2);
  });

  it("renders fenced code blocks verbatim", () => {
    mount("```\nwage = b0 + b1*edu\n```");
    expect(screen.getByTestId("md").querySelector("pre")).toHaveTextContent(
      "wage = b0 + b1*edu",
    );
  });

  it("routes every plain-text leaf through renderTextSpan (cite-chip seam), including inside bold", () => {
    const seen: string[] = [];
    mount("**R² = 0.73 [[c:c5]]** plus [[c:c9]]", (text, key) => {
      seen.push(text);
      return <span key={key}>{text.replace(/\[\[c:(\w+)\]\]/g, "CHIP($1)")}</span>;
    });
    const md = screen.getByTestId("md");
    expect(md.querySelector("strong")).toHaveTextContent("CHIP(c5)");
    expect(md.textContent).toContain("CHIP(c9)");
    expect(seen.join("")).toContain("[[c:c5]]");
  });

  it("handles hr and mixed document without crashing", () => {
    mount("# T\n\npara\n\n---\n\n- a\n- b continuation\n  next line\n\n## S2");
    expect(screen.getByTestId("md").querySelector("hr")).not.toBeNull();
  });
});
