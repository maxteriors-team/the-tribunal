"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { use, useCallback, useEffect, useRef, useState } from "react";

import { ClientProposalView } from "@/components/proposal/client-proposal-view";
import { parseProposalDocument } from "@/components/proposal/document";
import { PlainQuoteView } from "@/components/proposal/plain-quote-view";
import { DeadPublicLink } from "@/components/shared/dead-public-link";
import { PageLoadingState } from "@/components/ui/page-state";
import { publicProposalsApi } from "@/lib/api/public-proposals";
import { queryKeys } from "@/lib/query-keys";
import type { PublicProposal } from "@/types/proposal";

interface PublicProposalPageProps {
  params: Promise<{ token: string }>;
}

export default function PublicProposalPage({ params }: PublicProposalPageProps) {
  const { token } = use(params);
  const queryClient = useQueryClient();

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicProposals.byToken(token),
    queryFn: () => publicProposalsApi.get(token),
    enabled: !!token,
    retry: false,
  });

  const proposalDocument = parseProposalDocument(data?.proposal_document);
  const hasGreenSky =
    proposalDocument?.service === "permanent" && proposalDocument.green_sky !== null;

  const [payingDeposit, setPayingDeposit] = useState(false);

  // Hand off to Stripe's hosted deposit page. Shared by the standalone "Pay
  // Deposit" button and the "Approve & Pay Deposit" flow.
  const payDeposit = useCallback(async () => {
    setPayingDeposit(true);
    try {
      const { url } = await publicProposalsApi.depositCheckout(token);
      window.location.href = url;
    } catch {
      setPayingDeposit(false);
    }
  }, [token]);

  const approveMutation = useMutation({
    // The client submits the terms version rendered on this page. A racing seller
    // edit gets a 409 and a refetch instead of accepting prices they never saw.
    mutationFn: (selectedTier: string | null) => {
      if (!data) throw new Error("Proposal is still loading");
      return publicProposalsApi.approve(token, data.proposal_version, selectedTier);
    },
    onSuccess: (result) => {
      queryClient.setQueryData<PublicProposal | undefined>(
        queryKeys.publicProposals.byToken(token),
        (prev) => (prev ? { ...prev, status: result.status, is_decided: true } : prev),
      );
      // GreenSky proposals keep both next steps visible after acceptance. Every
      // legacy deposit flow still rolls straight into Stripe.
      if (result.deposit_required && !hasGreenSky) void payDeposit();
    },
    onError: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.publicProposals.byToken(token),
      });
    },
  });

  const declineMutation = useMutation({
    mutationFn: (reason?: string) => publicProposalsApi.decline(token, reason || undefined),
    onSuccess: (result) => {
      queryClient.setQueryData<PublicProposal | undefined>(
        queryKeys.publicProposals.byToken(token),
        (prev) => (prev ? { ...prev, status: result.status, is_decided: true } : prev),
      );
    },
  });

  // Tell the operator a human is reading this right now. Fires once per mount
  // (the ref survives React's StrictMode double-invoke in dev) and never from a
  // staff "Preview client proposal", which opens the exact customer URL with
  // `?preview=1` appended — without that skip, every internal peek would fire a
  // false "your client just opened it" alert.
  //
  // The flag is client-controlled and is not a security boundary. It does not
  // need to be: forging it only makes a real view go *unrecorded*, which costs a
  // notification, not a leak or a spoofed alert.
  const viewRecordedRef = useRef(false);
  useEffect(() => {
    if (viewRecordedRef.current || !token) return;
    viewRecordedRef.current = true;
    if (new URLSearchParams(window.location.search).get("preview") === "1") return;
    void publicProposalsApi.recordView(token);
  }, [token]);

  // Reliable deposit capture: on return from Stripe (``?deposit=paid``) the
  // webhook may not have landed yet. Reconcile against Stripe directly and poll
  // a few times with backoff until the deposit reads paid, so a delayed or
  // missing webhook never strands a paid deposit as "unpaid".
  const reconciledRef = useRef(false);
  useEffect(() => {
    if (reconciledRef.current) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("deposit") !== "paid") return;
    reconciledRef.current = true;
    let cancelled = false;
    void (async () => {
      for (let attempt = 0; attempt < 5 && !cancelled; attempt += 1) {
        try {
          const status = await publicProposalsApi.depositStatus(token);
          if (status.deposit_paid) {
            await queryClient.invalidateQueries({
              queryKey: queryKeys.publicProposals.byToken(token),
            });
            return;
          }
        } catch {
          // Ignore and retry; the button state degrades gracefully.
        }
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, queryClient]);

  if (isPending) {
    return (
      <div className="min-h-screen bg-[#0a0a0a]">
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !data) {
    return <DeadPublicLink subject="proposal" />;
  }

  const busy = approveMutation.isPending || declineMutation.isPending || payingDeposit;
  const justApproved = approveMutation.isSuccess || data.status === "approved";
  const justDeclined = declineMutation.isSuccess || data.status === "declined";
  const actionError = approveMutation.isError || declineMutation.isError;
  // Rich proposals (landscape, permanent, bistro, christmas) render the
  // multi-tier presentation; plain line-item quotes render the itemized quote.
  // Both share the dark/gold client theme so every recipient sees one brand.
  if (proposalDocument) {
    return (
      <ClientProposalView
        data={data}
        document={proposalDocument}
        justApproved={justApproved}
        justDeclined={justDeclined}
        busy={busy}
        actionError={actionError}
        onApprove={(selectedTier) => approveMutation.mutate(selectedTier)}
        onDecline={(reason) => declineMutation.mutate(reason)}
      />
    );
  }

  return (
    <PlainQuoteView
      data={data}
      justApproved={justApproved}
      justDeclined={justDeclined}
      busy={busy}
      actionError={actionError}
      onApprove={() => approveMutation.mutate(null)}
      onDecline={(reason) => declineMutation.mutate(reason)}
    />
  );
}
