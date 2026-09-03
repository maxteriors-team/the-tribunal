import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type PublicReferralPartnerIntake as PublicReferralPartnerIntakeData,
  type ReferralPartnerLogo,
} from "@/lib/api/referral-partners";

import { PublicReferralPartnerIntake } from "./public-referral-partner-intake";

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  submit: vi.fn(),
  uploadLogo: vi.fn(),
}));

vi.mock("@/lib/api/referral-partners", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/referral-partners")>(
    "@/lib/api/referral-partners",
  );
  return {
    ...actual,
    publicReferralPartnerIntakeApi: {
      ...actual.publicReferralPartnerIntakeApi,
      get: apiMocks.get,
      submit: apiMocks.submit,
      uploadLogo: apiMocks.uploadLogo,
    },
  };
});

const prefill: PublicReferralPartnerIntakeData = {
  name: "Taylor Partner",
  company: "Taylor Home Services",
  partner_type: "trade",
  email: "taylor@example.com",
  phone: "+1 (555) 555-1212",
  website_url: "https://taylor.example.com",
  business_description: "A trusted local home-services business.",
  services: "Maintenance and repair",
  service_area: "Greater Denver",
  offer_headline: "$100 service credit",
  offer_description: "A credit toward the first booked service.",
  offer_type: "fixed_dollar_credit",
  offer_value: 100,
  offer_terms: "New customers only.",
  intake_status: "pending",
  intake_submitted_at: null,
  has_logo: false,
};

const logoResponse: ReferralPartnerLogo = {
  content_type: "image/png",
  size_bytes: 3,
  created_at: "2026-09-02T12:00:00Z",
  updated_at: "2026-09-02T12:00:00Z",
};

function renderIntake() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PublicReferralPartnerIntake capability="intake-test-token" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PublicReferralPartnerIntake", () => {
  it("loads safe prefill and submits the profile before its logo", async () => {
    apiMocks.get.mockResolvedValue(prefill);
    apiMocks.submit.mockResolvedValue({
      ...prefill,
      intake_status: "submitted",
      intake_submitted_at: "2026-09-02T12:00:00Z",
    });
    apiMocks.uploadLogo.mockResolvedValue(logoResponse);
    const user = userEvent.setup();

    renderIntake();

    expect(await screen.findByLabelText("Your name")).toHaveValue("Taylor Partner");
    expect(screen.getByLabelText("Company")).toHaveValue("Taylor Home Services");
    expect(screen.getByLabelText("Offer headline")).toHaveValue("$100 service credit");

    const logo = new File(["png"], "logo.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Logo file"), logo);
    await user.click(screen.getByRole("button", { name: "Submit profile" }));

    expect(await screen.findByText("Thank you. Your profile is complete")).toBeInTheDocument();
    expect(apiMocks.submit).toHaveBeenCalledWith(
      "intake-test-token",
      expect.objectContaining({
        name: "Taylor Partner",
        company: "Taylor Home Services",
        offer_type: "fixed_dollar_credit",
        offer_value: 100,
      }),
    );
    expect(apiMocks.uploadLogo).toHaveBeenCalledWith("intake-test-token", logo);
    expect(apiMocks.submit.mock.invocationCallOrder[0]).toBeLessThan(
      apiMocks.uploadLogo.mock.invocationCallOrder[0],
    );
  });

  it("submits a value-free offer without validating the disabled amount", async () => {
    const complimentaryPrefill = {
      ...prefill,
      offer_type: "complimentary_service" as const,
      offer_value: null,
    };
    apiMocks.get.mockResolvedValue(complimentaryPrefill);
    apiMocks.submit.mockResolvedValue({
      ...complimentaryPrefill,
      intake_status: "submitted",
      intake_submitted_at: "2026-09-02T12:00:00Z",
    });
    apiMocks.uploadLogo.mockResolvedValue(logoResponse);
    const user = userEvent.setup();

    renderIntake();

    expect(await screen.findByLabelText("Offer type")).toHaveValue("complimentary_service");
    const logo = new File(["png"], "logo.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Logo file"), logo);
    await user.click(screen.getByRole("button", { name: "Submit profile" }));

    expect(await screen.findByText("Thank you. Your profile is complete")).toBeInTheDocument();
    expect(apiMocks.submit).toHaveBeenCalledWith(
      "intake-test-token",
      expect.objectContaining({
        offer_type: "complimentary_service",
        offer_value: null,
      }),
    );
  });

  it("shows a durable invalid-link state for an expired or revoked capability", async () => {
    apiMocks.get.mockRejectedValue({
      isAxiosError: true,
      message: "Not found",
      response: { status: 404 },
    });

    renderIntake();

    expect(await screen.findByText("This intake link is no longer available")).toBeInTheDocument();
    expect(screen.getByText(/expired or been replaced/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("focuses the required logo when submission is blocked", async () => {
    apiMocks.get.mockResolvedValue(prefill);
    const user = userEvent.setup();

    renderIntake();
    const input = await screen.findByLabelText("Logo file");
    await user.click(screen.getByRole("button", { name: "Submit profile" }));

    expect(await screen.findByText("A PNG, JPEG, or WebP logo is required.")).toBeInTheDocument();
    expect(input).toHaveFocus();
    expect(apiMocks.submit).not.toHaveBeenCalled();
  });

  it("rejects unsupported and oversized logo files before submission", async () => {
    apiMocks.get.mockResolvedValue(prefill);
    const user = userEvent.setup({ applyAccept: false });

    renderIntake();
    const input = await screen.findByLabelText("Logo file");

    await user.upload(input, new File(["pdf"], "logo.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Choose a PNG, JPEG, or WebP image.")).toBeInTheDocument();

    const oversized = new File([new Uint8Array(2 * 1024 * 1024 + 1)], "large.png", {
      type: "image/png",
    });
    await user.upload(input, oversized);
    expect(await screen.findByText("Logo must be 2 MiB or smaller.")).toBeInTheDocument();
    expect(apiMocks.submit).not.toHaveBeenCalled();
    expect(apiMocks.uploadLogo).not.toHaveBeenCalled();
  });

  it("keeps the saved profile and offers a logo-only retry after upload failure", async () => {
    apiMocks.get.mockResolvedValue(prefill);
    apiMocks.submit.mockResolvedValue({ ...prefill, intake_status: "submitted" });
    apiMocks.uploadLogo
      .mockRejectedValueOnce(new Error("Upload failed"))
      .mockResolvedValueOnce(logoResponse);
    const user = userEvent.setup();

    renderIntake();
    const logo = new File(["png"], "logo.png", { type: "image/png" });
    await user.upload(await screen.findByLabelText("Logo file"), logo);
    await user.click(screen.getByRole("button", { name: "Submit profile" }));

    expect(
      await screen.findByText("Your profile was saved, but the logo needs attention"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry logo upload" }));

    expect(await screen.findByText("Thank you. Your profile is complete")).toBeInTheDocument();
    expect(apiMocks.submit).toHaveBeenCalledTimes(1);
    expect(apiMocks.uploadLogo).toHaveBeenCalledTimes(2);
  });
});
