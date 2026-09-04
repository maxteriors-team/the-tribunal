"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  ExternalLink,
  FileCheck2,
  Link2,
  Loader2,
  RefreshCw,
  Unlink,
} from "lucide-react";
import Image from "next/image";
import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  referralPartnersApi,
  type ReferralPartner,
  type ReferralPartnerIntakeLink,
  type ReferralPartnerIntakeStatus,
  type ReferralPartnerOfferType,
} from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

const STATUS_LABELS: Record<ReferralPartnerIntakeStatus, string> = {
  not_requested: "Not requested",
  pending: "Awaiting submission",
  submitted: "Submitted",
  revoked: "Link revoked",
};

const OFFER_LABELS: Record<ReferralPartnerOfferType, string> = {
  none: "No numeric offer",
  fixed_dollar_credit: "Dollar credit",
  percentage_discount: "Percentage discount",
  complimentary_service: "Complimentary service",
  free_upgrade_add_on: "Free upgrade or add-on",
  gift: "Gift",
  other: "Other offer",
};

function formatDate(value: string | null): string | null {
  if (!value) return null;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

function offerValue(partner: ReferralPartner, currency: string): string | null {
  if (partner.offer_value === null) return null;
  if (partner.offer_type === "percentage_discount") return `${partner.offer_value}%`;
  if (partner.offer_type === "fixed_dollar_credit") {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
    }).format(partner.offer_value);
  }
  return String(partner.offer_value);
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="whitespace-pre-wrap text-sm">{children || "Not provided"}</dd>
    </div>
  );
}

async function copyToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  document.body.append(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  textArea.remove();
  if (!copied) throw new Error("Copy command was rejected");
}

export function ReferralPartnerIntakePanel({
  partner,
  workspaceId,
  currency,
  canManage,
}: {
  partner: ReferralPartner;
  workspaceId: string;
  currency: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [link, setLink] = useState<ReferralPartnerIntakeLink | null>(null);
  const [copied, setCopied] = useState(false);

  const refreshPartner = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.referralPartners.detail(workspaceId, partner.id),
    });

  const issueMutation = useMutation({
    mutationFn: () => referralPartnersApi.issueIntakeLink(workspaceId, partner.id),
    onSuccess: (created) => {
      setLink(created);
      void refreshPartner();
    },
    onError: (error) =>
      toast.error(getApiErrorMessage(error, "Couldn’t generate the intake link.")),
  });

  const rotateMutation = useMutation({
    mutationFn: () => referralPartnersApi.rotateIntakeLink(workspaceId, partner.id),
    onSuccess: (created) => {
      setLink(created);
      setCopied(false);
      void refreshPartner();
      toast.success("A new intake link is ready. The previous link no longer works.");
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn’t rotate the intake link.")),
  });

  const revokeMutation = useMutation({
    mutationFn: () => referralPartnersApi.revokeIntakeLink(workspaceId, partner.id),
    onSuccess: () => {
      setLink(null);
      setCopied(false);
      void refreshPartner();
      toast.success("Intake link revoked.");
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn’t revoke the intake link.")),
  });

  async function copyLink(existing?: string) {
    let value = existing;
    if (!value) {
      try {
        value = (await issueMutation.mutateAsync()).intake_url;
      } catch {
        return;
      }
    }
    try {
      await copyToClipboard(value);
      setCopied(true);
      toast.success("Intake link copied.");
    } catch {
      toast.error("The link is ready, but it couldn’t be copied. Copy it from the field instead.");
    }
  }

  const status = link?.status ?? partner.intake_status;
  const submittedAt = formatDate(partner.intake_submitted_at);
  const hasActiveLink = status === "pending" || status === "submitted";
  const isMutating =
    issueMutation.isPending || rotateMutation.isPending || revokeMutation.isPending;
  const hasSubmittedProfile =
    partner.intake_status === "submitted" ||
    Boolean(partner.website_url || partner.business_description || partner.offer_headline);
  const value = offerValue(partner, currency);

  return (
    <div className="space-y-6">
      <section aria-labelledby="partner-intake-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="partner-intake-heading" className="text-sm font-medium">
            Partner intake
          </h2>
          <Badge variant="outline" className="gap-1.5">
            <FileCheck2 className="size-3" aria-hidden />
            {STATUS_LABELS[status]}
          </Badge>
        </div>
        <div className="space-y-4 rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">
            {status === "not_requested"
              ? "Generate a secure 30-day link for this partner to submit their business profile, customer offer, and logo."
              : status === "pending"
                ? "The intake link is active and the partner has not submitted their profile yet."
                : status === "submitted"
                  ? `Profile received${submittedAt ? ` ${submittedAt}` : ""}. The link can still be used to send updates.`
                  : "The previous intake link has been revoked and no longer works."}
          </div>

          {canManage && partner.is_active ? (
            <div className="flex flex-wrap gap-2">
              {!hasActiveLink ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isMutating}
                  onClick={() => issueMutation.mutate()}
                >
                  {issueMutation.isPending ? (
                    <Loader2 className="mr-1.5 size-4 animate-spin" aria-hidden />
                  ) : (
                    <Link2 className="mr-1.5 size-4" aria-hidden />
                  )}
                  Generate intake link
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isMutating}
                  onClick={() => void copyLink(link?.intake_url)}
                >
                  {issueMutation.isPending ? (
                    <Loader2 className="mr-1.5 size-4 animate-spin" aria-hidden />
                  ) : copied ? (
                    <Check className="mr-1.5 size-4" aria-hidden />
                  ) : (
                    <Copy className="mr-1.5 size-4" aria-hidden />
                  )}
                  {copied ? "Copied" : "Copy intake link"}
                </Button>
              )}

              {hasActiveLink ? (
                <>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="sm" variant="outline" disabled={isMutating}>
                        <RefreshCw className="mr-1.5 size-4" aria-hidden />
                        Rotate link
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Replace the current intake link?</AlertDialogTitle>
                        <AlertDialogDescription>
                          The current link will stop working immediately. You’ll need to send the
                          new link to the partner.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => rotateMutation.mutate()}>
                          Rotate link
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>

                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="sm" variant="outline" disabled={isMutating}>
                        <Unlink className="mr-1.5 size-4" aria-hidden />
                        Revoke link
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Revoke this intake link?</AlertDialogTitle>
                        <AlertDialogDescription>
                          The partner will no longer be able to open or submit this form. Their
                          previously submitted profile stays on the partner record.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          onClick={() => revokeMutation.mutate()}
                        >
                          Revoke link
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </>
              ) : null}
            </div>
          ) : null}

          {link ? (
            <div className="space-y-2 rounded-md bg-muted/50 p-3">
              <div className="flex gap-2">
                <Input value={link.intake_url} readOnly aria-label="Referral partner intake link" />
                <Button
                  size="icon"
                  variant="outline"
                  onClick={() => void copyLink(link.intake_url)}
                >
                  <Copy className="size-4" aria-hidden />
                  <span className="sr-only">Copy link</span>
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Expires {formatDate(link.expires_at)}. This URL grants access to the partner
                form—share it only with the intended partner.
              </p>
            </div>
          ) : null}
        </div>
      </section>

      <section aria-labelledby="submitted-profile-heading" className="space-y-3">
        <h2 id="submitted-profile-heading" className="text-sm font-medium">
          Submitted profile and offer
        </h2>
        {!hasSubmittedProfile ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            No intake profile has been submitted yet.
          </div>
        ) : (
          <div className="space-y-5 rounded-lg border p-4">
            <div className="flex flex-col gap-5 sm:flex-row">
              {partner.has_logo ? (
                <div className="flex size-28 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-white p-2">
                  <Image
                    src={referralPartnersApi.logoUrl(workspaceId, partner.id)}
                    alt={`${partner.company || partner.name} logo`}
                    width={112}
                    height={112}
                    unoptimized
                    className="max-h-full max-w-full object-contain"
                  />
                </div>
              ) : (
                <div className="flex size-28 shrink-0 items-center justify-center rounded-lg border border-dashed text-center text-xs text-muted-foreground">
                  No logo submitted
                </div>
              )}
              <dl className="grid flex-1 gap-4 sm:grid-cols-2">
                <Detail label="Contact name">{partner.name}</Detail>
                <Detail label="Company">{partner.company}</Detail>
                <Detail label="Email">{partner.email}</Detail>
                <Detail label="Phone">{partner.phone}</Detail>
                <Detail label="Website">
                  {partner.website_url ? (
                    <a
                      href={partner.website_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 underline-offset-4 hover:underline"
                    >
                      {partner.website_url}
                      <ExternalLink className="size-3" aria-hidden />
                    </a>
                  ) : null}
                </Detail>
                <Detail label="Service area">{partner.service_area}</Detail>
              </dl>
            </div>
            <dl className="grid gap-4 border-t pt-4 sm:grid-cols-2">
              <Detail label="Business description">{partner.business_description}</Detail>
              <Detail label="Services">{partner.services}</Detail>
            </dl>
            <div className="space-y-4 border-t pt-4">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-medium">{partner.offer_headline || "Customer offer"}</h3>
                <Badge variant="secondary">{OFFER_LABELS[partner.offer_type]}</Badge>
                {value ? <Badge variant="outline">{value}</Badge> : null}
              </div>
              <dl className="grid gap-4 sm:grid-cols-2">
                <Detail label="Offer description">{partner.offer_description}</Detail>
                <Detail label="Offer terms">{partner.offer_terms}</Detail>
              </dl>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
