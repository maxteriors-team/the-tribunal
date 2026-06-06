import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SpeedToLeadBadge,
  type SpeedToLeadProof,
} from "@/components/landing/speed-to-lead-badge";

function mockFetch(proof: SpeedToLeadProof | null, ok = true): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      json: () => Promise.resolve(proof),
    }),
  );
}

const enabledProof: SpeedToLeadProof = {
  enabled: true,
  sla_seconds: 60,
  window_days: 30,
  leads_measured: 120,
  pct_within_sla: 98.7,
  median_response_seconds: 12,
  headline: "98.7% of leads answered in under 60s",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SpeedToLeadBadge", () => {
  it("renders the headline when the badge is enabled", async () => {
    mockFetch(enabledProof);
    render(<SpeedToLeadBadge publicKey="ls_abc123" />);
    await waitFor(() =>
      expect(
        screen.getByText("98.7% of leads answered in under 60s"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("speed-to-lead-badge")).toBeInTheDocument();
  });

  it("renders nothing when the badge is disabled", async () => {
    mockFetch({ ...enabledProof, enabled: false, headline: null });
    const { container } = render(<SpeedToLeadBadge publicKey="ls_abc123" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="speed-to-lead-badge"]')).toBeNull();
  });

  it("renders nothing when the request fails", async () => {
    mockFetch(null, false);
    const { container } = render(<SpeedToLeadBadge publicKey="ls_abc123" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });
});
