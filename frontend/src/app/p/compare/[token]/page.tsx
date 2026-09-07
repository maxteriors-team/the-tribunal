"use client";

import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import { use } from "react";

import { ComparisonCard } from "@/components/estimator/comparison-card";
import { proposalAccentVars } from "@/components/proposal/proposal-brand";
import { DeadPublicLink } from "@/components/shared/dead-public-link";
import { PageLoadingState } from "@/components/ui/page-state";
import { publicComparisonsApi } from "@/lib/api/public-comparisons";
import { clientThemeClass } from "@/lib/estimator/services";
import { queryKeys } from "@/lib/query-keys";

import "@/components/estimator/estimator.css";

interface PublicComparisonPageProps {
  params: Promise<{ token: string }>;
}

export default function PublicComparisonPage({ params }: PublicComparisonPageProps) {
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
    return <DeadPublicLink subject="comparison" />;
  }

  // Keep the legacy seasonal atmosphere, then apply validated workspace colors
  // inline so the tenant's own identity remains authoritative.
  const theme = clientThemeClass(data.christmas.enabled ? ["christmas"] : []);

  // Seasonal Good/Better/Best ladder (feet-free totals only). The recommended
  // tier (rep's pick, else most-inclusive) also labels the summary seasonal card
  // so the comparison and the package grid agree on the highlighted package.
  const packages = data.christmas_packages ?? [];
  const recommended = packages.find((pkg) => pkg.recommended) ?? null;

  return (
    <div
      className={`cmp-view ${theme}`.trim()}
      style={proposalAccentVars(data.brand_color, data.accent_color)}
    >
      <div className="cmp-public-brand">
        {data.logo_url ? (
          <Image src={data.logo_url} alt={data.business_name} width={220} height={64} unoptimized />
        ) : (
          <strong>{data.business_name}</strong>
        )}
      </div>
      <ComparisonCard
        legacyPreview
        view={{
          currency: data.currency,
          clientName: data.client_name,
          discountAmount: data.discount_amount,
          permanent: data.permanent,
          // Feet-free by construction: `christmas.total` already reflects the
          // recommended Good/Better/Best package (folded server-side), and
          // `christmasName` labels that tier from the package payload — still no
          // per-ft or feet, so the client sees prices, never the measurement.
          christmas: data.christmas,
          christmasName: recommended ? (recommended.name ?? recommended.label) : null,
          difference: data.difference,
          years: data.years,
          temporary_multi_year: data.temporary_multi_year,
          permanent_one_time: data.permanent_one_time,
          multi_year_savings: data.multi_year_savings,
          permanent_perks: data.permanent_perks,
          christmas_perks: data.christmas_perks,
          christmasPackages: packages.map((pkg) => ({
            key: pkg.key,
            name: pkg.name ?? pkg.label,
            marker: pkg.marker,
            total: pkg.total,
            valueTag: pkg.value_tag,
            popular: pkg.popular,
            recommended: pkg.recommended,
            points: pkg.points,
            experience: pkg.experience,
          })),
          // Roofline-only cost comparison; null unless the workspace turned it on
          // and sells both options, so the default page is unchanged. Costs only.
          roofline: data.roofline,
          // Add-ons the rep put on this estimate, itemized so a price the
          // homeowner didn't expect always has a line that explains it.
          customLines: data.custom_lines,
        }}
      />
    </div>
  );
}
