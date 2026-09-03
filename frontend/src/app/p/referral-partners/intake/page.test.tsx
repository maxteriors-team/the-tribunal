import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReferralPartnerIntakePage from "./page";

vi.mock("@/components/referral-partners/public-referral-partner-intake", () => ({
  PublicReferralPartnerIntake: ({ capability }: { capability: string }) => (
    <div data-testid="intake-capability">{capability}</div>
  ),
}));

const STORAGE_KEY = "referral-partner-intake-token";
const TOKEN = "abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ-1234";

describe("ReferralPartnerIntakePage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, "", "/p/referral-partners/intake");
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("extracts the fragment capability, removes it from the URL, and keeps refresh support", async () => {
    window.history.replaceState({}, "", `/p/referral-partners/intake#token=${TOKEN}`);

    render(<ReferralPartnerIntakePage />);

    expect(await screen.findByTestId("intake-capability")).toHaveTextContent(TOKEN);
    expect(window.location.hash).toBe("");
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe(TOKEN);
  });

  it("restores a previously extracted capability without placing it in the URL", async () => {
    window.sessionStorage.setItem(STORAGE_KEY, TOKEN);

    render(<ReferralPartnerIntakePage />);

    expect(await screen.findByTestId("intake-capability")).toHaveTextContent(TOKEN);
    expect(window.location.hash).toBe("");
  });

  it.each([
    ["malformed", "not a token"],
    ["oversized", "x".repeat(129)],
  ])("rejects a %s fragment and clears an older stored capability", async (_label, token) => {
    window.sessionStorage.setItem(STORAGE_KEY, TOKEN);
    window.history.replaceState({}, "", `/p/referral-partners/intake#token=${token}`);

    render(<ReferralPartnerIntakePage />);

    await waitFor(() => {
      expect(screen.getByText("This intake link is invalid")).toBeInTheDocument();
    });
    expect(window.location.hash).toBe("");
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
