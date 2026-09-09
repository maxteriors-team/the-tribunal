import { beforeEach, describe, expect, it } from "vitest";

import {
  buildScreenTroubleshootPrompt,
  clearDiagnostics,
  describeDiagnostics,
  getDiagnostics,
  recordApiFailure,
  recordDiagnostic,
  safePath,
} from "@/lib/assistant/diagnostics";

describe("diagnostics", () => {
  beforeEach(() => {
    clearDiagnostics();
  });

  it("strips query strings, which carry invite and share tokens", () => {
    expect(safePath("/p/compare/abc?token=secret-value")).toBe("/p/compare/abc");
    expect(safePath("https://api.example.com/api/v1/contacts?q=jane#frag")).toBe(
      "/api/v1/contacts",
    );
    expect(safePath("")).toBe("unknown");
  });

  it("records API failures as method, path and status only", () => {
    recordApiFailure({
      method: "post",
      url: "/api/v1/workspaces/w1/contacts?secret=abc",
      status: 500,
      message: "Request failed",
    });

    expect(getDiagnostics()).toHaveLength(1);
    expect(getDiagnostics()[0]).toMatchObject({
      source: "network",
      detail: "POST /api/v1/workspaces/w1/contacts → 500",
    });
  });

  it("falls back to the transport message when there is no response", () => {
    recordApiFailure({ method: "get", url: "/api/v1/contacts", message: "Network Error" });
    expect(getDiagnostics()[0].detail).toBe("GET /api/v1/contacts → Network Error");
  });

  it("ignores auth probes, whose 401s are routine when signed out", () => {
    recordApiFailure({ method: "get", url: "/api/v1/auth/me", status: 401 });
    expect(getDiagnostics()).toHaveLength(0);
  });

  it("keeps only the most recent entries", () => {
    for (let index = 0; index < 20; index += 1) recordDiagnostic("script", `boom ${index}`);

    const entries = getDiagnostics();
    expect(entries).toHaveLength(8);
    expect(entries[0].detail).toBe("boom 12");
    expect(entries.at(-1)?.detail).toBe("boom 19");
  });

  it("truncates long details so one error cannot flood the prompt", () => {
    recordDiagnostic("script", "x".repeat(1000));
    expect(getDiagnostics()[0].detail).toHaveLength(200);
  });

  it("describes nothing when no failures were recorded", () => {
    expect(describeDiagnostics()).toBe("");
    expect(buildScreenTroubleshootPrompt("/contacts")).toBe(
      "Troubleshoot what I'm looking at in this screenshot. Tell me what's wrong and how to fix it.\n\nPage: /contacts",
    );
  });

  it("builds a prompt carrying the page and recent failures", () => {
    recordApiFailure({ method: "get", url: "/api/v1/workspaces/w1/contacts", status: 500 });

    const prompt = buildScreenTroubleshootPrompt("/contacts", Date.now() + 5_000);

    expect(prompt).toContain("Page: /contacts");
    expect(prompt).toContain("- network: GET /api/v1/workspaces/w1/contacts → 500 (5s ago)");
  });
});
