"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { use } from "react";

import { ClientProposalView } from "@/components/proposal/client-proposal-view";
import { parseProposalDocument } from "@/components/proposal/document";
import { PlainQuoteView } from "@/components/proposal/plain-quote-view";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { publicProposalsApi } from "@/lib/api/public-proposals";
import { queryKeys } from "@/lib/query-keys";
import type { PublicProposal } from "@/types/proposal";

interface PublicProposalPageProps {
  params: Promise<{ token: string }>;
}

export default function PublicProposalPage({
  params,
}: PublicProposalPageProps) {
  const { token } = use(params);
  const queryClient = useQueryClient();

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicProposals.byToken(token),
    queryFn: () => publicProposalsApi.get(token),
    enabled: !!token,
    retry: false,
  });

  const approveMutation = useMutation({
    mutationFn: () => publicProposalsApi.approve(token),
    onSuccess: (result) => {
      queryClient.setQueryData<PublicProposal | undefined>(
        queryKeys.publicProposals.byToken(token),
        (prev) =>
          prev
            ? { ...prev, status: result.status, is_decided: true }
            : prev,
      );
    },
  });

  const declineMutation = useMutation({
    mutationFn: (reason?: string) =>
      publicProposalsApi.decline(token, reason || undefined),
    onSuccess: (result) => {
      queryClient.setQueryData<PublicProposal | undefined>(
        queryKeys.publicProposals.byToken(token),
        (prev) =>
          prev
            ? { ...prev, status: result.status, is_decided: true }
            : prev,
      );
    },
  });

  if (isPending) {
    return (
      <div className="min-h-screen bg-[#0a0a0a]">
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-[#0a0a0a]">
        <PageErrorState
          className="min-h-screen"
          message="This proposal link is invalid or has expired."
        />
      </div>
    );
  }

  const busy = approveMutation.isPending || declineMutation.isPending;
  const justApproved = approveMutation.isSuccess || data.status === "approved";
  const justDeclined = declineMutation.isSuccess || data.status === "declined";
  const actionError = approveMutation.isError || declineMutation.isError;
  // Builder proposals (landscape, permanent, bistro, christmas) render the
  // multi-tier presentation; plain line-item quotes render the itemized quote.
  // Both share the dark/gold client theme so every recipient sees one brand.
  const proposalDocument = parseProposalDocument(data.proposal_document);

  if (proposalDocument) {
    return (
      <ClientProposalView
        data={data}
        document={proposalDocument}
        justApproved={justApproved}
        justDeclined={justDeclined}
        busy={busy}
        actionError={actionError}
        onApprove={() => approveMutation.mutate()}
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
      onApprove={() => approveMutation.mutate()}
      onDecline={(reason) => declineMutation.mutate(reason)}
    />
  );
}
