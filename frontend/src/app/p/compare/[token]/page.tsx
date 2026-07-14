"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";

import { ComparisonCard } from "@/components/estimator/comparison-card";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { publicComparisonsApi } from "@/lib/api/public-comparisons";
import { queryKeys } from "@/lib/query-keys";

import "@/components/estimator/estimator.css";

interface PublicComparisonPageProps {
  params: Promise<{ token: string }>;
}

export default function PublicComparisonPage({
  params,
}: PublicComparisonPageProps) {
  const { token } = use(params);

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicComparisons.byToken(token),
    queryFn: () => publicComparisonsApi.get(token),
    enabled: !!token,
    retry: false,
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
          message="This comparison link is invalid or has expired."
        />
      </div>
    );
  }

  // Apply the workspace brand accent to the scoped theme.
  const brandStyle = {
    ["--gold" as string]: data.accent_color || data.brand_color,
  } as React.CSSProperties;

  return (
    <div className="cmp-view" style={brandStyle}>
      {data.business_name ? (
        <div style={{ textAlign: "center", paddingTop: 32 }}>
          <span className="cmp-brand">{data.business_name}</span>
        </div>
      ) : null}
      <ComparisonCard
        view={{
          currency: data.currency,
          clientName: data.client_name,
          permanent: data.permanent,
          christmas: data.christmas,
          difference: data.difference,
          years: data.years,
          temporary_multi_year: data.temporary_multi_year,
          permanent_one_time: data.permanent_one_time,
          multi_year_savings: data.multi_year_savings,
          permanent_perks: data.permanent_perks,
          christmas_perks: data.christmas_perks,
        }}
      />
    </div>
  );
}
