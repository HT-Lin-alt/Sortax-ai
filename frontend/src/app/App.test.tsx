import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AppProvider } from "./AppProvider";

describe("App", () => {
  it("renders the mobile-first fixture shell", () => {
    window.history.pushState({}, "", "/?fixtures=1");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    expect(screen.getByRole("heading", { name: "Sortax" })).toBeInTheDocument();
    expect(screen.getByText("Fixture preview")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "A few details first" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Documents to gather" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tax information summary" })).toBeInTheDocument();
    expect(screen.getByLabelText("Message Sortax")).toBeDisabled();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });
});
