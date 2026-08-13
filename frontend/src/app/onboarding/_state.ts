import * as z from "zod";

/**
 * Onboarding form schema — the entire flow lives in a single react-hook-form
 * with `mode: "onTouched"`. Per-step validation runs via `form.trigger(fields)`.
 *
 * Non-form state (uploaded File, verified connection metadata) lives in
 * OnboardingExtrasContext — it isn't user-edited input.
 */
export const onboardingSchema = z.object({
  area_code: z.string().max(3),
});

export type OnboardingFormValues = z.infer<typeof onboardingSchema>;

export const ONBOARDING_DEFAULTS: OnboardingFormValues = {
  area_code: "",
};

export const STEP_IDS = ["calendar", "leads", "review"] as const;
export type OnboardingStepId = (typeof STEP_IDS)[number];

/**
 * Fields each step is responsible for validating before advancing.
 * `leads` and `review` have no form fields — leads validates via the
 * extras context (csv upload), review just submits.
 */
export const STEP_FIELDS = {
  calendar: [],
  leads: [],
  review: [],
} as const satisfies Record<OnboardingStepId, readonly (keyof OnboardingFormValues)[]>;
