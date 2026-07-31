/**
 * Form → API payload mapping for the pre-booking wizard.
 *
 * The offer half of this mapping talks to a backend schema declared
 * `extra="forbid"`, so a stray wizard-only field (`example_job_amount`) is a 422
 * at the end of an eight-step form. The launch half decides whether the campaign
 * waits for its season or starts sending today, which is the entire feature.
 *
 * The audience half is exercised through the rendered step, because what can go
 * wrong there is not arithmetic: last season's holiday-lighting slice is far
 * narrower than "any past customer", so it must stay off unless the operator
 * asks for it, and its count must be readable while it is still off.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreBookingAudiencePreview } from "@/types";

import {
  buildInitialPreBookingFormData,
  buildPreBookingSubmission,
  type PreBookingFormData,
} from "./pre-booking-campaign-wizard";
import { makeAudienceStep, validateAudience } from "./pre-booking-steps";

const { previewAudienceMock } = vi.hoisted(() => ({
  previewAudienceMock: vi.fn(),
}));

vi.mock("@/lib/api/pre-booking-campaigns", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/pre-booking-campaigns")
  >("@/lib/api/pre-booking-campaigns");
  return {
    ...actual,
    preBookingApi: {
      ...actual.preBookingApi,
      previewWorkspaceAudience: previewAudienceMock,
    },
  };
});

function formData(overrides: Partial<PreBookingFormData> = {}): PreBookingFormData {
  return {
    ...buildInitialPreBookingFormData(new Date("2026-09-01T12:00:00Z")),
    name: "Spring 2027 Pre-Book",
    from_phone_number: "+15550001111",
    initial_message: "Hi {first_name}, lock in spring at 15% off",
    service_description: "Spring house wash + gutter clean",
    ...overrides,
  };
}

describe("buildPreBookingSubmission", () => {
  it("sends the offer exactly as the backend schema declares it", () => {
    const { offer } = buildPreBookingSubmission(formData());

    expect(offer).toEqual({
      service_season_start_month: 3,
      service_season_end_month: 5,
      service_season_year: 2027,
      service_description: "Spring house wash + gutter clean",
      incentive_type: "percentage",
      incentive_value: 15,
      deposit_type: "percentage",
      deposit_value: 25,
      slot_cap: 20,
      hold_hours: 72,
    });
  });

  it("never leaks the worked example's job price into the offer", () => {
    const { offer } = buildPreBookingSubmission(
      formData({ example_job_amount: 1234 }),
    );
    expect(offer).not.toHaveProperty("example_job_amount");
  });

  it("trims the service description that becomes the quote and job title", () => {
    const { offer } = buildPreBookingSubmission(
      formData({ service_description: "  Spring house wash  " }),
    );
    expect(offer.service_description).toBe("Spring house wash");
  });

  it("creates an ordinary SMS campaign — pre-booking is not a channel", () => {
    const { campaign } = buildPreBookingSubmission(formData());

    expect(campaign.name).toBe("Spring 2027 Pre-Book");
    expect(campaign.from_phone_number).toBe("+15550001111");
    expect(campaign.initial_message).toContain("lock in spring");
    expect(campaign).not.toHaveProperty("campaign_type");
    expect(campaign).not.toHaveProperty("service_season_start_month");
  });

  it("drops empty optional strings rather than sending blanks", () => {
    const { campaign } = buildPreBookingSubmission(
      formData({ description: "", qualification_criteria: "", follow_up_message: "" }),
    );

    expect(campaign.description).toBeUndefined();
    expect(campaign.qualification_criteria).toBeUndefined();
    expect(campaign.follow_up_message).toBeUndefined();
  });

  it("passes the chosen launch date through as an ISO instant", () => {
    const { scheduledStart } = buildPreBookingSubmission(
      formData({ scheduled_start: "2026-09-15T09:00", start_immediately: false }),
    );

    expect(scheduledStart).toBe(new Date("2026-09-15T09:00").toISOString());
  });

  it("reports no launch date when the operator starts immediately", () => {
    const { scheduledStart } = buildPreBookingSubmission(
      formData({ scheduled_start: "2026-09-15T09:00", start_immediately: true }),
    );

    expect(scheduledStart).toBeNull();
  });

  it("carries the warm-audience choice through to the enrol call", () => {
    const { audience } = buildPreBookingSubmission(
      formData({ include_past_customers: true, include_unsold_quotes: false }),
    );

    expect(audience).toEqual({
      include_past_customers: true,
      include_unsold_quotes: false,
      include_prior_season_christmas: false,
    });
  });

  it("enrols only last season's lit homes on a renewal push", () => {
    const { audience } = buildPreBookingSubmission(
      formData({
        include_past_customers: false,
        include_unsold_quotes: false,
        include_prior_season_christmas: true,
      }),
    );

    expect(audience).toEqual({
      include_past_customers: false,
      include_unsold_quotes: false,
      include_prior_season_christmas: true,
    });
  });
});

describe("buildInitialPreBookingFormData", () => {
  it("prefills next spring when this spring has already been and gone", () => {
    const data = buildInitialPreBookingFormData(new Date("2026-09-01T12:00:00Z"));

    expect(data.service_season_start_month).toBe(3);
    expect(data.service_season_end_month).toBe(5);
    expect(data.service_season_year).toBe(2027);
  });

  it("keeps this year's spring while it is still ahead", () => {
    const data = buildInitialPreBookingFormData(new Date("2026-01-10T12:00:00Z"));
    expect(data.service_season_year).toBe(2026);
  });

  it("defaults to an offer that is a booking, not a coupon", () => {
    const data = buildInitialPreBookingFormData();

    expect(data.deposit_value).toBeGreaterThan(0);
    expect(data.slot_cap).toBeGreaterThan(0);
    expect(data.include_past_customers).toBe(true);
    expect(data.include_unsold_quotes).toBe(true);
  });

  it("leaves last season's lighting customers off until asked for", () => {
    // The narrow slice must never widen the default audience: a spring
    // pre-book is not a Christmas renewal.
    expect(
      buildInitialPreBookingFormData().include_prior_season_christmas,
    ).toBe(false);
  });
});

function preview(
  overrides: Partial<PreBookingAudiencePreview> = {},
): PreBookingAudiencePreview {
  return {
    total: 412,
    past_customers: 300,
    unsold_quotes: 120,
    prior_season_christmas: 143,
    excluded_opted_out: 9,
    excluded_already_enrolled: 0,
    ...overrides,
  };
}

/**
 * The audience step as the wizard drives it: real wizard defaults in, real
 * `updateField` semantics back out, so a toggle here proves what the enrol call
 * would be sent.
 */
function AudienceHarness({
  overrides = {},
}: {
  overrides?: Partial<PreBookingFormData>;
}) {
  const [data, setData] = useState<PreBookingFormData>(() => formData(overrides));
  const step = useMemo(
    () =>
      makeAudienceStep<"audience", PreBookingFormData>({
        id: "audience",
        workspaceId: "ws-1",
      }),
    [],
  );

  return (
    <>
      {step.render({
        formData: data,
        errors: {},
        updateField: (key, value) =>
          setData((prev) => ({ ...prev, [key]: value })),
      })}
    </>
  );
}

function renderAudienceStep(overrides: Partial<PreBookingFormData> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AudienceHarness overrides={overrides} />
    </QueryClientProvider>,
  );
}

const seasonalSwitch = () =>
  screen.getByRole("switch", { name: /holiday-lighting customers/i });

describe("audience step: last season's holiday-lighting customers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    previewAudienceMock.mockResolvedValue(preview());
  });

  it("shows how many homes were lit last season while the slice is still off", async () => {
    renderAudienceStep();

    // The server counts every slice whether or not it is selected, so the
    // operator sizes the renewal list before committing to it.
    expect(await screen.findByText(/143 lit last season/)).toBeInTheDocument();
    expect(seasonalSwitch()).not.toBeChecked();
  });

  it("is off by default, unlike the two broad slices", async () => {
    renderAudienceStep();

    await waitFor(() =>
      expect(previewAudienceMock).toHaveBeenCalledWith("ws-1", {
        include_past_customers: true,
        include_unsold_quotes: true,
        include_prior_season_christmas: false,
      }),
    );
    expect(seasonalSwitch()).not.toBeChecked();
    expect(
      screen.getByRole("switch", { name: /past customers/i }),
    ).toBeChecked();
  });

  it("asks for the slice once the operator turns it on", async () => {
    const user = userEvent.setup();
    renderAudienceStep();

    await user.click(seasonalSwitch());

    // Sizing is debounced, so the request trails the click.
    await waitFor(
      () =>
        expect(previewAudienceMock).toHaveBeenLastCalledWith(
          "ws-1",
          expect.objectContaining({ include_prior_season_christmas: true }),
        ),
      { timeout: 2000 },
    );
    expect(seasonalSwitch()).toBeChecked();
  });

  it("sizes a renewal push with the broad slices switched off", async () => {
    renderAudienceStep({
      include_past_customers: false,
      include_unsold_quotes: false,
      include_prior_season_christmas: true,
    });

    await waitFor(() =>
      expect(previewAudienceMock).toHaveBeenCalledWith("ws-1", {
        include_past_customers: false,
        include_unsold_quotes: false,
        include_prior_season_christmas: true,
      }),
    );
    // ...and the step accepts it: the narrow slice is an audience on its own.
    expect(
      validateAudience({
        include_past_customers: false,
        include_unsold_quotes: false,
        include_prior_season_christmas: true,
      }),
    ).toEqual({});
  });
});
