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

  // The festive palette is fixed (warm gold / holly / evergreen) so the holiday
  // page stays cohesive for every workspace regardless of its brand color; the
  // business is identified by its name text rather than a brand accent that
  // could clash with the theme.

  // Seasonal Good/Better/Best ladder (feet-free totals only). The recommended
  // tier (rep's pick, else most-inclusive) also labels the summary seasonal card
  // so the comparison and the package grid agree on the highlighted package.
  const packages = data.christmas_packages ?? [];
  const recommended = packages.find((pkg) => pkg.recommended) ?? null;

  return (
    <div className="cmp-view cmp-festive">
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
          // Feet-free by construction: `christmas.total` already reflects the
          // recommended Good/Better/Best package (folded server-side), and
          // `christmasName` labels that tier from the package payload — still no
          // per-ft or feet, so the client sees prices, never the measurement.
          christmas: data.christmas,
          christmasName: recommended
            ? (recommended.name ?? recommended.label)
            : null,
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
        }}
      />
    </div>
  );
}
