"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, ImageUp, Loader2 } from "lucide-react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  publicReferralPartnerIntakeApi,
  type PublicReferralPartnerIntake,
  type PublicReferralPartnerIntakeSubmit,
  type ReferralPartnerOfferType,
} from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage, getApiErrorStatus } from "@/lib/utils/errors";

export const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const ALLOWED_LOGO_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

export function validateReferralPartnerLogo(file: File): string | null {
  if (!ALLOWED_LOGO_TYPES.has(file.type)) {
    return "Choose a PNG, JPEG, or WebP image.";
  }
  if (file.size === 0) return "The selected image is empty.";
  if (file.size > MAX_LOGO_BYTES) return "Logo must be 2 MiB or smaller.";
  return null;
}

const requiredText = (label: string, max: number) =>
  z.string().trim().min(1, `${label} is required.`).max(max, `${label} is too long.`);

const intakeSchema = z
  .object({
    name: requiredText("Name", 200),
    company: requiredText("Company", 200),
    email: z.string().trim().min(1, "Email is required.").email("Enter a valid email address."),
    phone: z
      .string()
      .trim()
      .min(1, "Phone is required.")
      .regex(/^[0-9+()\-. xX]{7,32}$/, "Enter a valid phone number."),
    website_url: z
      .string()
      .trim()
      .min(1, "Website is required.")
      .max(2048, "Website URL is too long.")
      .url("Enter a full website URL, including https://.")
      .refine((value) => value.startsWith("https://") || value.startsWith("http://"), {
        message: "Website must start with http:// or https://.",
      }),
    business_description: requiredText("Business description", 5000),
    services: requiredText("Services", 5000),
    service_area: requiredText("Service area", 500),
    offer_headline: requiredText("Offer headline", 200),
    offer_description: requiredText("Offer description", 3000),
    offer_type: z.enum([
      "none",
      "fixed_dollar_credit",
      "percentage_discount",
      "complimentary_service",
      "free_upgrade_add_on",
      "gift",
      "other",
    ]),
    offer_value: z.number().positive("Offer value must be greater than zero.").nullable(),
    offer_terms: requiredText("Offer terms", 3000),
  })
  .superRefine((values, context) => {
    const requiresValue =
      values.offer_type === "fixed_dollar_credit" || values.offer_type === "percentage_discount";
    if (requiresValue && values.offer_value === null) {
      context.addIssue({
        code: "custom",
        path: ["offer_value"],
        message: "Offer value is required for this offer type.",
      });
    }
    if (values.offer_type === "percentage_discount" && (values.offer_value ?? 0) > 100) {
      context.addIssue({
        code: "custom",
        path: ["offer_value"],
        message: "Percentage must be 100 or less.",
      });
    }
  });

type IntakeFormValues = z.infer<typeof intakeSchema>;

type SubmissionStage = "idle" | "profile" | "logo" | "complete" | "partial";

const OFFER_TYPES: ReadonlyArray<{ value: ReferralPartnerOfferType; label: string }> = [
  { value: "fixed_dollar_credit", label: "Dollar credit" },
  { value: "percentage_discount", label: "Percentage discount" },
  { value: "complimentary_service", label: "Complimentary service" },
  { value: "free_upgrade_add_on", label: "Free upgrade or add-on" },
  { value: "gift", label: "Gift" },
  { value: "other", label: "Other offer" },
  { value: "none", label: "No numeric offer" },
];

function valuesFromPrefill(prefill: PublicReferralPartnerIntake): IntakeFormValues {
  return {
    name: prefill.name,
    company: prefill.company ?? "",
    email: prefill.email ?? "",
    phone: prefill.phone ?? "",
    website_url: prefill.website_url ?? "",
    business_description: prefill.business_description ?? "",
    services: prefill.services ?? "",
    service_area: prefill.service_area ?? "",
    offer_headline: prefill.offer_headline ?? "",
    offer_description: prefill.offer_description ?? "",
    offer_type: prefill.offer_type,
    offer_value: prefill.offer_value === null ? null : Number(prefill.offer_value),
    offer_terms: prefill.offer_terms ?? "",
  };
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p className="text-sm text-destructive" role="alert">
      {message}
    </p>
  );
}

function FormField({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      <FieldError message={error} />
    </div>
  );
}

export function PublicReferralPartnerIntake({ capability }: { capability: string }) {
  const [queryInstanceId] = useState(() => crypto.randomUUID());
  const intakeQuery = useQuery({
    queryKey: queryKeys.referralPartners.publicIntake(queryInstanceId),
    queryFn: () => publicReferralPartnerIntakeApi.get(capability),
    retry: false,
    gcTime: 0,
  });

  if (intakeQuery.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-12">
        <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-5 animate-spin" aria-hidden />
          Loading your profile form…
        </div>
      </main>
    );
  }

  if (intakeQuery.isError || !intakeQuery.data) {
    const unavailable = getApiErrorStatus(intakeQuery.error) === 404;
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-12">
        <Card className="w-full max-w-lg text-center">
          <CardHeader>
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-destructive/10">
              <AlertCircle className="size-6 text-destructive" aria-hidden />
            </div>
            <CardTitle>
              {unavailable
                ? "This intake link is no longer available"
                : "We couldn’t load this form"}
            </CardTitle>
            <CardDescription>
              {unavailable
                ? "The link may have expired or been replaced. Ask your contact for a new referral-partner intake link."
                : "Check your connection and try again. If the problem continues, contact the person who sent this link."}
            </CardDescription>
          </CardHeader>
          {!unavailable ? (
            <CardContent>
              <Button variant="outline" onClick={() => void intakeQuery.refetch()}>
                Try again
              </Button>
            </CardContent>
          ) : null}
        </Card>
      </main>
    );
  }

  return <IntakeForm capability={capability} prefill={intakeQuery.data} />;
}

function IntakeForm({
  capability,
  prefill,
}: {
  capability: string;
  prefill: PublicReferralPartnerIntake;
}) {
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [logoError, setLogoError] = useState<string | null>(null);
  const [logoLinkUnavailable, setLogoLinkUnavailable] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [stage, setStage] = useState<SubmissionStage>("idle");
  const [retryingLogo, setRetryingLogo] = useState(false);
  const [existingLogoUrl, setExistingLogoUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!prefill.has_logo) return;

    let disposed = false;
    let objectUrl: string | null = null;
    void publicReferralPartnerIntakeApi
      .getLogo(capability)
      .then((logo) => {
        objectUrl = URL.createObjectURL(logo);
        if (disposed) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setExistingLogoUrl(objectUrl);
      })
      .catch(() => {
        // A stale logo flag should not prevent the partner from replacing it.
      });

    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [capability, prefill.has_logo]);
  const form = useForm<IntakeFormValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues: valuesFromPrefill(prefill),
  });
  const offerType = useWatch({ control: form.control, name: "offer_type" });
  const offerNeedsValue =
    offerType === "fixed_dollar_credit" || offerType === "percentage_discount";
  const busy = stage === "profile" || stage === "logo";

  function chooseLogo(file: File | undefined) {
    if (!file) {
      setLogoFile(null);
      setLogoError(prefill.has_logo ? null : "A logo is required.");
      return;
    }
    const error = validateReferralPartnerLogo(file);
    if (error) {
      setLogoFile(null);
      setLogoError(error);
      return;
    }
    setLogoFile(file);
    setLogoError(null);
  }

  async function uploadLogo(showUploadStage = true): Promise<boolean> {
    if (!logoFile) return prefill.has_logo;
    if (showUploadStage) setStage("logo");
    try {
      await publicReferralPartnerIntakeApi.uploadLogo(capability, logoFile);
      return true;
    } catch (error) {
      const expired = getApiErrorStatus(error) === 404;
      setLogoLinkUnavailable(expired);
      setLogoError(
        expired
          ? "Your profile was saved, but this link expired before the logo uploaded. Ask for a new link to finish."
          : getApiErrorMessage(error, "Your profile was saved, but the logo did not upload."),
      );
      setStage("partial");
      return false;
    }
  }

  async function submit(values: IntakeFormValues) {
    if (!logoFile && !prefill.has_logo) {
      setLogoError("A PNG, JPEG, or WebP logo is required.");
      document.getElementById("logo")?.focus();
      return;
    }

    setSubmitError(null);
    setStage("profile");
    const payload: PublicReferralPartnerIntakeSubmit = {
      ...values,
      offer_value: offerNeedsValue ? values.offer_value : null,
    };
    try {
      await publicReferralPartnerIntakeApi.submit(capability, payload);
    } catch (error) {
      setSubmitError(getApiErrorMessage(error, "We couldn’t save your profile. Please try again."));
      setStage("idle");
      return;
    }

    const uploaded = await uploadLogo();
    if (uploaded) setStage("complete");
  }

  async function retryLogo() {
    if (!logoFile) {
      setLogoError("Choose a PNG, JPEG, or WebP logo to retry.");
      return;
    }
    setLogoError(null);
    setRetryingLogo(true);
    const uploaded = await uploadLogo(false);
    setRetryingLogo(false);
    if (uploaded) setStage("complete");
  }

  if (stage === "complete") {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-12">
        <Card className="w-full max-w-lg text-center">
          <CardHeader>
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-success/10">
              <CheckCircle2 className="size-6 text-success" aria-hidden />
            </div>
            <CardTitle>Thank you. Your profile is complete</CardTitle>
            <CardDescription>
              Your business details, customer offer, and logo have been received. You can safely
              close this page.
            </CardDescription>
          </CardHeader>
        </Card>
      </main>
    );
  }

  if (stage === "partial") {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-12">
        <Card className="w-full max-w-lg">
          <CardHeader>
            <div className="mb-2 flex size-12 items-center justify-center rounded-full bg-warning/10">
              <ImageUp className="size-6 text-warning" aria-hidden />
            </div>
            <CardTitle>Your profile was saved, but the logo needs attention</CardTitle>
            <CardDescription>
              Your business and offer details are safe. Retry the logo upload below. This will not
              resubmit the profile.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert variant="destructive">
              <AlertCircle className="size-4" aria-hidden />
              <AlertTitle>Logo not uploaded</AlertTitle>
              <AlertDescription>{logoError}</AlertDescription>
            </Alert>
            {!logoLinkUnavailable ? (
              <>
                <FormField
                  label="Choose a different logo"
                  htmlFor="retry-logo"
                  hint="PNG, JPEG, or WebP · 2 MiB maximum"
                >
                  <Input
                    id="retry-logo"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={(event) => chooseLogo(event.currentTarget.files?.[0])}
                  />
                </FormField>
                <Button className="w-full" onClick={() => void retryLogo()} disabled={retryingLogo}>
                  {retryingLogo ? (
                    <Loader2 className="mr-2 size-4 animate-spin" aria-hidden />
                  ) : null}
                  {retryingLogo ? "Retrying logo upload…" : "Retry logo upload"}
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Ask your contact for a new intake link, then open it to upload the logo.
              </p>
            )}
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-background px-4 py-8 sm:py-12">
      <div className="mx-auto w-full max-w-3xl space-y-6">
        <header className="text-center">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Referral partner profile</h1>
            <p className="mt-2 text-muted-foreground">
              Help customers understand your business and the exclusive offer available to them.
            </p>
          </div>
        </header>

        <form className="space-y-6" noValidate onSubmit={form.handleSubmit(submit)}>
          <Card>
            <CardHeader>
              <CardTitle>Business details</CardTitle>
              <CardDescription>
                Tell us who customers should contact and where you work.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <FormField
                label="Your name"
                htmlFor="name"
                error={form.formState.errors.name?.message}
              >
                <Input id="name" autoComplete="name" {...form.register("name")} />
              </FormField>
              <FormField
                label="Company"
                htmlFor="company"
                error={form.formState.errors.company?.message}
              >
                <Input id="company" autoComplete="organization" {...form.register("company")} />
              </FormField>
              <FormField label="Email" htmlFor="email" error={form.formState.errors.email?.message}>
                <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
              </FormField>
              <FormField label="Phone" htmlFor="phone" error={form.formState.errors.phone?.message}>
                <Input id="phone" type="tel" autoComplete="tel" {...form.register("phone")} />
              </FormField>
              <FormField
                className="sm:col-span-2"
                label="Website"
                htmlFor="website_url"
                error={form.formState.errors.website_url?.message}
                hint="Include https:// or http://"
              >
                <Input
                  id="website_url"
                  type="url"
                  autoComplete="url"
                  placeholder="https://example.com"
                  {...form.register("website_url")}
                />
              </FormField>
              <FormField
                className="sm:col-span-2"
                label="Business description"
                htmlFor="business_description"
                error={form.formState.errors.business_description?.message}
              >
                <Textarea
                  id="business_description"
                  rows={4}
                  placeholder="What makes your business a great choice?"
                  {...form.register("business_description")}
                />
              </FormField>
              <FormField
                className="sm:col-span-2"
                label="Services"
                htmlFor="services"
                error={form.formState.errors.services?.message}
              >
                <Textarea
                  id="services"
                  rows={3}
                  placeholder="List the services customers can book."
                  {...form.register("services")}
                />
              </FormField>
              <FormField
                className="sm:col-span-2"
                label="Service area"
                htmlFor="service_area"
                error={form.formState.errors.service_area?.message}
              >
                <Textarea
                  id="service_area"
                  rows={2}
                  placeholder="Cities, counties, or radius served"
                  {...form.register("service_area")}
                />
              </FormField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Exclusive client offer</CardTitle>
              <CardDescription>
                Describe exactly what referred customers receive and any limits.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <FormField
                className="sm:col-span-2"
                label="Offer headline"
                htmlFor="offer_headline"
                error={form.formState.errors.offer_headline?.message}
              >
                <Input
                  id="offer_headline"
                  placeholder="Save $100 on your first service"
                  {...form.register("offer_headline")}
                />
              </FormField>
              <FormField
                className="sm:col-span-2"
                label="Offer description"
                htmlFor="offer_description"
                error={form.formState.errors.offer_description?.message}
              >
                <Textarea
                  id="offer_description"
                  rows={3}
                  placeholder="Explain what is included and how customers redeem it."
                  {...form.register("offer_description")}
                />
              </FormField>
              <FormField
                label="Offer type"
                htmlFor="offer_type"
                error={form.formState.errors.offer_type?.message}
              >
                <select
                  id="offer_type"
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  {...form.register("offer_type", {
                    onChange: (event) => {
                      const next = event.target.value as ReferralPartnerOfferType;
                      if (next !== "fixed_dollar_credit" && next !== "percentage_discount") {
                        form.setValue("offer_value", null, { shouldValidate: true });
                      }
                    },
                  })}
                >
                  {OFFER_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField
                label={offerType === "percentage_discount" ? "Offer value (%)" : "Offer value ($)"}
                htmlFor="offer_value"
                error={form.formState.errors.offer_value?.message}
                hint={
                  !offerNeedsValue
                    ? "A numeric value is not needed for this offer type."
                    : undefined
                }
              >
                <Input
                  id="offer_value"
                  type="number"
                  min="0.01"
                  max={offerType === "percentage_discount" ? "100" : undefined}
                  step="0.01"
                  disabled={!offerNeedsValue}
                  {...form.register("offer_value", {
                    setValueAs: (value) =>
                      value === "" || value === null || value === undefined ? null : Number(value),
                  })}
                />
              </FormField>
              <FormField
                className="sm:col-span-2"
                label="Offer terms"
                htmlFor="offer_terms"
                error={form.formState.errors.offer_terms?.message}
              >
                <Textarea
                  id="offer_terms"
                  rows={3}
                  placeholder="Expiration, eligibility, exclusions, and redemption instructions"
                  {...form.register("offer_terms")}
                />
              </FormField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Company logo</CardTitle>
              <CardDescription>
                {prefill.has_logo
                  ? "A logo is already on file. Choose a new image only if you want to replace it."
                  : "Upload the logo customers should see with your offer."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {existingLogoUrl ? (
                <Image
                  src={existingLogoUrl}
                  alt="Current company logo"
                  width={512}
                  height={128}
                  unoptimized
                  className="mb-4 max-h-32 max-w-full rounded-md border object-contain p-2"
                />
              ) : null}
              <FormField
                label="Logo file"
                htmlFor="logo"
                error={logoError ?? undefined}
                hint="PNG, JPEG, or WebP · 2 MiB maximum"
              >
                <Input
                  id="logo"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  aria-invalid={Boolean(logoError)}
                  onChange={(event) => chooseLogo(event.currentTarget.files?.[0])}
                />
              </FormField>
            </CardContent>
          </Card>

          {submitError ? (
            <Alert variant="destructive">
              <AlertCircle className="size-4" aria-hidden />
              <AlertTitle>Profile not saved</AlertTitle>
              <AlertDescription>{submitError}</AlertDescription>
            </Alert>
          ) : null}

          <Button type="submit" size="lg" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="mr-2 size-4 animate-spin" aria-hidden /> : null}
            {stage === "profile"
              ? "Saving profile…"
              : stage === "logo"
                ? "Uploading logo…"
                : prefill.intake_status === "submitted"
                  ? "Update profile"
                  : "Submit profile"}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Maxteriors stores these details to manage referrals and present your approved offer to
            customers.
          </p>
        </form>
      </div>
    </main>
  );
}
