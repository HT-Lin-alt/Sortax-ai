import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafeMarkdown } from "./SafeMarkdown";

describe("SafeMarkdown", () => {
  it("renders headings, bold text, line breaks and lists", () => {
    render(<SafeMarkdown>{"## Tax records\nKeep **receipts**.\nKeep statements.\n\n- First item\n- Second item"}</SafeMarkdown>);

    expect(screen.getByRole("heading", { name: "Tax records" })).toBeInTheDocument();
    expect(screen.getByText("receipts")).toHaveProperty("tagName", "STRONG");
    expect(screen.getByText("Keep statements.").firstChild).toHaveProperty("tagName", "BR");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("normalizes over-escaped bold markers without injecting HTML", () => {
    const { container } = render(<SafeMarkdown>{String.raw`\*\*\*\*标题\*\*\*\* <script>alert(1)</script>`}</SafeMarkdown>);

    expect(screen.getByText("标题")).toHaveProperty("tagName", "STRONG");
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
  });

  it("creates only HTTPS links", () => {
    render(<SafeMarkdown>{"[ATO](https://www.ato.gov.au) [unsafe](javascript:alert(1))"}</SafeMarkdown>);

    expect(screen.getByRole("link", { name: "ATO" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "unsafe" })).not.toBeInTheDocument();
  });
});
