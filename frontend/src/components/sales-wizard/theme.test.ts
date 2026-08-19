import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(
  resolve(process.cwd(), "src/components/sales-wizard/theme.css"),
  "utf8",
);

describe("sales wizard changed-scope accessibility CSS", () => {
  it("stacks proposal link and delivery controls on narrow screens", () => {
    const mobile = css.match(/@media \(max-width: 520px\) \{[\s\S]*?\n  \}/g)?.join("\n") ?? "";

    expect(mobile).toContain(".share-link-row { flex-direction: column; }");
    expect(mobile).toContain(".share-link-copy, .share-send-btn");
    expect(mobile).toContain("min-height: 44px");
  });

  it("leaves a visible keyboard focus indicator on every wizard control", () => {
    expect(css).toContain(
      ".sales-wizard :is(button, a, input, select, textarea):focus-visible",
    );
    expect(css).toContain("outline: 3px solid var(--gold-l)");
  });
});
