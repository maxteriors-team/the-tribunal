import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReferralPartner, ReferralPartnerIntakeLink } from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";

import { ReferralPartnerIntakePanel } from "./referral-partner-intake-panel";

const mocks = vi.hoisted(() => ({
  issueIntakeLink: vi.fn(),
  rotateIntakeLink: vi.fn(),
  revokeIntakeLink: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/lib/api/referral-partners", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/referral-partners")>(
    "@/lib/api/referral-partners",
  );
  return {
    ...actual,
    referralPartnersApi: {
      ...actual.referralPartnersApi,
      issueIntakeLink: mocks.issueIntakeLink,
      rotateIntakeLink: mocks.rotateIntakeLink,
      revokeIntakeLink: mocks.revokeIntakeLink,
    },
  };
});

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

const intakeLink: ReferralPartnerIntakeLink = {
  intake_url: "https://app.example.com/p/referral-partners/intake#token=intake-token",
  created_at: "2026-09-02T12:00:00Z",
  expires_at: "2026-10-02T12:00:00Z",
  status: "pending",
};

function makePartner(overrides: Partial<ReferralPartner> = {}): ReferralPartner {
  return {
    id: "partner-1",
    workspace_id: "workspace-1",
    name: "Taylor Partner",
    company: "Taylor Home Services",
    partner_type: "trade",
    email: "taylor@example.com",
    phone: "+1 (555) 555-1212",
    notes: null,
    contact_id: null,
    is_active: true,
    website_url: "https://taylor.example.com",
    business_description: "A trusted local home-services business.",
    services: "Maintenance and repair",
    service_area: "Greater Denver",
    offer_headline: "$100 service credit",
    offer_description: "A credit toward the first booked service.",
    offer_type: "fixed_dollar_credit",
    offer_value: 100,
    offer_terms: "New customers only.",
    intake_status: "submitted",
    intake_link_created_at: "2026-09-02T12:00:00Z",
    intake_submitted_at: "2026-09-02T13:00:00Z",
    intake_revoked_at: null,
    has_logo: true,
    created_at: "2026-08-01T12:00:00Z",
    updated_at: "2026-09-02T13:00:00Z",
    ...overrides,
  };
}

function renderPanel({
  partner = makePartner(),
  canManage = true,
}: {
  partner?: ReferralPartner;
  canManage?: boolean;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <ReferralPartnerIntakePanel
          partner={partner}
          workspaceId="workspace-1"
          currency="USD"
          canManage={canManage}
        />
      </QueryClientProvider>,
    ),
    invalidateQueries,
  };
}

beforeEach(() => {
  mocks.issueIntakeLink.mockReset();
  mocks.rotateIntakeLink.mockReset();
  mocks.revokeIntakeLink.mockReset();
  mocks.toastError.mockReset();
  mocks.toastSuccess.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReferralPartnerIntakePanel", () => {
  it("displays the submitted profile, customer offer, and logo", () => {
    renderPanel();

    const heading = screen.getByRole("heading", { name: "Submitted profile and offer" });
    const section = heading.closest("section");
    if (!section) throw new Error("Submitted profile section was not rendered");
    const profile = within(section);

    expect(profile.getByRole("img", { name: "Taylor Home Services logo" })).toHaveAttribute(
      "src",
      "/api/v1/workspaces/workspace-1/referral-partners/partner-1/logo",
    );
    expect(profile.getByText("Taylor Partner")).toBeInTheDocument();
    expect(profile.getByText("Taylor Home Services")).toBeInTheDocument();
    expect(profile.getByText("taylor@example.com")).toBeInTheDocument();
    expect(profile.getByText("Greater Denver")).toBeInTheDocument();
    expect(profile.getByRole("link", { name: /taylor\.example\.com/ })).toHaveAttribute(
      "href",
      "https://taylor.example.com",
    );
    expect(profile.getByText("A trusted local home-services business.")).toBeInTheDocument();
    expect(profile.getByText("Maintenance and repair")).toBeInTheDocument();
    expect(profile.getByRole("heading", { name: "$100 service credit" })).toBeInTheDocument();
    expect(profile.getByText("Dollar credit")).toBeInTheDocument();
    expect(profile.getByText("$100.00")).toBeInTheDocument();
    expect(profile.getByText("New customers only.")).toBeInTheDocument();
  });

  it("hides issue and copy controls without write permission", () => {
    const { unmount } = renderPanel({
      partner: makePartner({
        intake_status: "not_requested",
        intake_link_created_at: null,
        intake_submitted_at: null,
      }),
      canManage: false,
    });

    expect(screen.queryByRole("button", { name: "Generate intake link" })).not.toBeInTheDocument();

    unmount();
    renderPanel({
      partner: makePartner({ intake_status: "pending", intake_submitted_at: null }),
      canManage: false,
    });

    expect(screen.queryByRole("button", { name: "Copy intake link" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rotate link" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke link" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Submitted profile and offer" }),
    ).toBeInTheDocument();
  });

  it("issues and copies an active intake link for a manager", async () => {
    mocks.issueIntakeLink.mockResolvedValue(intakeLink);
    const user = userEvent.setup();
    const clipboardWrite = vi.spyOn(navigator.clipboard, "writeText");
    const { invalidateQueries } = renderPanel({
      partner: makePartner({ intake_status: "pending", intake_submitted_at: null }),
    });

    await user.click(screen.getByRole("button", { name: "Copy intake link" }));

    expect(mocks.issueIntakeLink).toHaveBeenCalledWith("workspace-1", "partner-1");
    expect(await screen.findByLabelText("Referral partner intake link")).toHaveValue(
      intakeLink.intake_url,
    );
    expect(clipboardWrite).toHaveBeenCalledWith(intakeLink.intake_url);
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Intake link copied.");
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.referralPartners.detail("workspace-1", "partner-1"),
    });
  });

  it("rotates only after confirmation and exposes the replacement link", async () => {
    const replacement = {
      ...intakeLink,
      intake_url: "https://app.example.com/p/referral-partners/intake#token=replacement-token",
    };
    mocks.rotateIntakeLink.mockResolvedValue(replacement);
    const user = userEvent.setup();
    const { invalidateQueries } = renderPanel({
      partner: makePartner({ intake_status: "pending", intake_submitted_at: null }),
    });

    await user.click(screen.getByRole("button", { name: "Rotate link" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Replace the current intake link?")).toBeInTheDocument();
    expect(mocks.rotateIntakeLink).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Rotate link" }));

    expect(mocks.rotateIntakeLink).toHaveBeenCalledWith("workspace-1", "partner-1");
    expect(await screen.findByLabelText("Referral partner intake link")).toHaveValue(
      replacement.intake_url,
    );
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      "A new intake link is ready. The previous link no longer works.",
    );
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.referralPartners.detail("workspace-1", "partner-1"),
    });
  });

  it("revokes only after confirmation and refreshes the partner", async () => {
    mocks.revokeIntakeLink.mockResolvedValue(undefined);
    const user = userEvent.setup();
    const { invalidateQueries } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Revoke link" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Revoke this intake link?")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/previously submitted profile stays on the partner record/i),
    ).toBeInTheDocument();
    expect(mocks.revokeIntakeLink).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Revoke link" }));

    await waitFor(() => {
      expect(mocks.revokeIntakeLink).toHaveBeenCalledWith("workspace-1", "partner-1");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Intake link revoked.");
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.referralPartners.detail("workspace-1", "partner-1"),
    });
  });
});
