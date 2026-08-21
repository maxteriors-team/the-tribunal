import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ProviderPageErrorState,
  resolveProviderSetupKind,
  type ProviderSetupKind,
} from "@/components/shared/provider-error-state";
import { ProviderNotConfiguredBanner } from "@/components/shared/provider-not-configured-banner";

const { canMock } = vi.hoisted(() => ({ canMock: vi.fn() }));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: canMock }),
}));

function apiError(code: string, provider?: string): unknown {
  return {
    response: {
      status: 503,
      data: {
        code,
        message: "Provider credentials are not configured",
        details: provider ? { provider } : undefined,
      },
    },
  };
}

beforeEach(() => {
  canMock.mockReset();
  canMock.mockReturnValue(true);
});

describe("ProviderPageErrorState", () => {
  it("links workspace managers directly to integration settings", () => {
    render(
      <ProviderPageErrorState
        error={apiError("telnyx_provider_not_configured", "telnyx")}
        provider="telnyx"
        transientTitle="Phone numbers are temporarily unavailable"
        transientMessage="Retry phone numbers."
        onRetry={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Connect Telnyx to manage phone numbers" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Set up Telnyx" })).toHaveAttribute(
      "href",
      "/settings?tab=integrations",
    );
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("hides setup links from roles that cannot manage integrations", () => {
    canMock.mockReturnValue(false);

    render(
      <ProviderPageErrorState
        error={apiError("openai_provider_not_configured", "openai")}
        provider="openai"
        transientTitle="AI leads are temporarily unavailable"
        transientMessage="Retry AI leads."
        onRetry={vi.fn()}
      />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/ask a workspace owner or admin/i)).toBeVisible();
  });

  it("keeps retry for transient provider failures", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    render(
      <ProviderPageErrorState
        error={{ response: { status: 503, data: { code: "provider_timeout" } } }}
        provider="people-search"
        transientTitle="People search is temporarily unavailable"
        transientMessage="The provider did not respond."
        onRetry={onRetry}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "People search is temporarily unavailable" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.queryByRole("link", { name: /set up/i })).not.toBeInTheDocument();
  });
});

describe("ProviderNotConfiguredBanner", () => {
  it("does not expose Settings to members", () => {
    canMock.mockReturnValue(false);

    render(
      <ProviderNotConfiguredBanner
        title="Lead search needs a provider"
        description="Connect it in Settings."
      />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/ask a workspace owner or admin/i)).toBeVisible();
  });
});

describe("resolveProviderSetupKind", () => {
  it.each<[string, string | undefined, ProviderSetupKind, ProviderSetupKind]>([
    ["telnyx_provider_not_configured", "telnyx", "scraping", "telnyx"],
    ["openai_provider_not_configured", "openai", "scraping", "openai"],
    ["ad_library_provider_unavailable", "meta_ad_library", "scraping", "ad-library"],
    ["scraping_provider_not_configured", "google_places", "scraping", "scraping"],
    ["people_search_provider_not_configured", "google_places", "people-search", "people-search"],
  ])("maps %s to its action-specific setup state", (code, provider, fallback, expected) => {
    expect(resolveProviderSetupKind(apiError(code, provider), fallback)).toBe(expected);
  });
});
