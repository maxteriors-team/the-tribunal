import * as z from "zod";

/**
 * Onboarding form schema — the entire flow lives in a single react-hook-form
 * with `mode: "onTouched"`. Per-step validation runs via `form.trigger(fields)`.
 *
 * Non-form state (uploaded File, verified connection metadata) lives in
 * OnboardingExtrasContext — it isn't user-edited input.
 */
export const onboardingSchema = z.object({
  calcom_api_key: z
    .string()
    .trim()
    .min(1, { error: "Cal.com API key is required." }),
  calcom_booking_url: z
    .string()
    .trim()
    .min(1, { error: "Booking URL is required." })
    .refine((v) => v.startsWith("https://cal.com/"), {
      error: 'URL must start with "https://cal.com/".',
    }),
  area_code: z.string().max(3),
});

export type OnboardingFormValues = z.infer<typeof onboardingSchema>;

export const ONBOARDING_DEFAULTS: OnboardingFormValues = {
  calcom_api_key: "",
  calcom_booking_url: "",
  area_code: "",
};

export const STEP_IDS = ["calcom", "leads", "review"] as const;
export type OnboardingStepId = (typeof STEP_IDS)[number];

/**
 * Fields each step is responsible for validating before advancing.
 * `leads` and `review` have no form fields — leads validates via the
 * extras context (csv upload), review just submits.
 */
export const STEP_FIELDS = {
  calcom: ["calcom_api_key", "calcom_booking_url"],
  leads: [],
  review: [],
} as const satisfies Record<OnboardingStepId, readonly (keyof OnboardingFormValues)[]>;
