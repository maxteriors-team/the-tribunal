"use client";

/**
 * New Email Campaign — styled to match the sales/quote builder ("index") look:
 * the scoped `.sales-wizard` dark/gold theme (Cormorant + Montserrat) for the
 * hand-built header, message fields, and action buttons. The shared
 * `VirtualContactSelector` is shadcn-based and can't live inside `.sales-wizard`
 * (its universal padding reset would break the component), so it renders in the
 * app's own `dark` theme on the same near-black surface for a cohesive result.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { VirtualContactSelector } from "@/components/campaigns/virtual-contact-selector";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { salesWizardFontVars } from "@/components/sales-wizard/fonts";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  emailCampaignsApi,
  type CreateEmailCampaignRequest,
} from "@/lib/api/email-campaigns";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

import "@/components/sales-wizard/theme.css";

export default function NewEmailCampaignPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const createMutation = useMutation({
    mutationFn: async ({ startNow }: { startNow: boolean }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");

      const data: CreateEmailCampaignRequest = {
        name: name.trim(),
        campaign_type: "email",
        email_subject: subject.trim(),
        initial_message: body.trim(),
      };
      const campaign = await emailCampaignsApi.create(workspaceId, data);

      const contactIds = Array.from(selectedIds);
      if (contactIds.length > 0) {
        await emailCampaignsApi.addContacts(workspaceId, campaign.id, contactIds);
      }
      if (startNow && contactIds.length > 0) {
        await emailCampaignsApi.start(workspaceId, campaign.id);
      }
      return campaign;
    },
    onSuccess: (campaign) => {
      toast.success(messages.campaigns.emailCreated);
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all(workspaceId) });
      }
      router.push(`/campaigns/${campaign.id}`);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.campaigns.emailCreateFailed));
    },
  });

  const canSubmit =
    !!workspaceId &&
    name.trim().length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    !createMutation.isPending;

  const recipientCopy =
    selectedIds.size > 0
      ? `${selectedIds.size} contact${selectedIds.size === 1 ? "" : "s"} selected`
      : "Choose who should receive this email";

  return (
    <AppSidebar>
      <div
        className={`dark h-full overflow-y-auto ${salesWizardFontVars}`}
        style={{ background: "#0a0a0a" }}
      >
        {/* Themed top nav */}
        <div className="sales-wizard" style={{ minHeight: 0 }}>
          <div className="present-nav">
            <Link href="/campaigns" className="back-btn">
              &#8592;&nbsp; Campaigns
            </Link>
            <div className="present-nav-brand">Email Campaign</div>
          </div>
        </div>

        <div style={{ maxWidth: 680, margin: "0 auto", padding: "40px 24px 100px" }}>
          {/* Header + message fields (hand-built → safe inside .sales-wizard) */}
          <div className="sales-wizard" style={{ minHeight: 0 }}>
            <div className="calc-header" style={{ marginBottom: 32 }}>
              <div className="calc-wordmark">
                <div className="calc-wordmark-line" />
                <div className="calc-wordmark-text">Maxteriors</div>
                <div className="calc-wordmark-line" />
              </div>
              <div className="calc-title">
                <em>Email</em>&nbsp;Campaign
              </div>
              <div className="calc-rule" />
              <div className="calc-sub">
                Compose the broadcast, choose recipients, then send
              </div>
            </div>

            <div className="fields-block">
              <div className="fields-block-label">Message</div>

              <div className="field-wrap" style={{ marginBottom: 18 }}>
                <label className="field-label" htmlFor="name">
                  Campaign Name
                </label>
                <input
                  id="name"
                  className="field-input"
                  placeholder="July Newsletter"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>

              <div className="field-wrap" style={{ marginBottom: 18 }}>
                <label className="field-label" htmlFor="subject">
                  Subject Line
                </label>
                <input
                  id="subject"
                  className="field-input"
                  placeholder="Hi {first_name}, an update from Maxteriors"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </div>

              <div className="field-wrap">
                <label className="field-label" htmlFor="body">
                  Email Body
                </label>
                <textarea
                  id="body"
                  className="field-input"
                  rows={10}
                  placeholder="Write your message here…"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  style={{
                    border: "1px solid var(--bdr)",
                    background: "var(--black)",
                    padding: "12px 14px",
                    lineHeight: 1.6,
                    resize: "vertical",
                  }}
                />
                <div className="wizard-copy" style={{ marginTop: 10 }}>
                  Use {"{first_name}"} and {"{company_name}"} to personalize the
                  subject and body. An unsubscribe link is added automatically to
                  every email (required for marketing mail).
                </div>
              </div>
            </div>

            {/* Recipients heading (themed); the selector itself sits below in dark */}
            <div style={{ marginTop: 20 }}>
              <div className="fields-block-label" style={{ marginBottom: 6 }}>
                Recipients
              </div>
              <div className="wizard-copy" style={{ marginBottom: 14 }}>
                {recipientCopy}
              </div>
            </div>
          </div>

          {/* Recipients selector — app dark theme (shadcn), outside .sales-wizard */}
          {workspaceId ? (
            <VirtualContactSelector
              workspaceId={workspaceId}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
            />
          ) : null}

          {/* Themed action buttons */}
          <div className="sales-wizard" style={{ minHeight: 0 }}>
            <div className="wizard-nav" style={{ marginTop: 24 }}>
              <button
                type="button"
                className="wizard-nav-btn secondary"
                onClick={() => createMutation.mutate({ startNow: false })}
                disabled={!canSubmit}
                style={{
                  opacity: canSubmit ? 1 : 0.5,
                  cursor: canSubmit ? "pointer" : "not-allowed",
                }}
              >
                Save as Draft
              </button>
              <button
                type="button"
                className="wizard-nav-btn primary"
                onClick={() => createMutation.mutate({ startNow: true })}
                disabled={!canSubmit || selectedIds.size === 0}
                style={{
                  opacity: !canSubmit || selectedIds.size === 0 ? 0.5 : 1,
                  cursor:
                    !canSubmit || selectedIds.size === 0
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                Create &amp; Send
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppSidebar>
  );
}
