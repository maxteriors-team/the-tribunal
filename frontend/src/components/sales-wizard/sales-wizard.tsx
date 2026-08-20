"use client";

/**
 * Sales Wizard root — hosts the quote builder inside the scoped `.sales-wizard`
 * dark/gold theme, plus the shared Light Designer for the photo work. All state
 * lives in `useSalesWizard`, which mirrors the selection to the backend for
 * authoritative pricing.
 *
 * Only two screens now: the builder and the full-bleed Light Designer. The
 * client presentation used to be a third, reached sideways from the review
 * step; it is a step of the builder itself ("Preview"), between pricing the
 * quote and sending it.
 *
 * The designer is the same component the Quotes hub renders, so there is one
 * photo tool: what the rep draws here saves onto the proposal and pushes its
 * measured fixtures and roofline feet back into this quote.
 */
import { BookOpen } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { LightDesigner } from "@/components/estimator/light-designer";
import type { DesignerProposalHost } from "@/components/estimator/proposal-host";
import { Button } from "@/components/ui/button";
import { PageEmptyState } from "@/components/ui/page-state";
import { resolveTierFixtures, type FixtureType } from "@/lib/estimator/fixtures";
import type { ServiceKey as DesignerServiceKey } from "@/lib/estimator/services";

import { CalculatorScreen } from "./calculator-screen";
import { salesWizardFontVars } from "./fonts";
import { hasSellableLandscapePackage } from "./sales-setup";
import { useSalesWizard, type ServiceKey } from "./use-sales-wizard";
import "./theme.css";

type Screen = "calc" | "design";

interface SalesWizardProps {
  workspaceId: string;
  brandName: string;
  brandLogoUrl?: string | null;
  /** Service branch to start on (deep-linked from the Quotes hub). */
  service?: ServiceKey;
  /** Existing quote opened from the quote list. */
  quoteId?: string | null;
}

export function SalesWizard({
  workspaceId,
  brandName,
  brandLogoUrl = null,
  service = "landscape",
  quoteId = null,
}: SalesWizardProps) {
  const wizard = useSalesWizard(workspaceId, service, quoteId);
  const [screen, setScreen] = useState<Screen>("calc");

  const show = (next: Screen) => {
    setScreen(next);
    window.scrollTo(0, 0);
  };

  const {
    night,
    setNight,
    setQty,
    setChristmas,
    hasCategory,
    toggleCategory,
    activeService,
    activeTier,
    pricing,
    catalog,
  } = wizard;
  const hasSellablePackage = hasSellableLandscapePackage(pricing, catalog);

  // The quote's own service seeds the designer's toggle, so opening the tool
  // from a Christmas quote starts on Christmas rather than landscape.
  const initialServices = useMemo<DesignerServiceKey[]>(
    () => (night.services.length ? night.services : [activeService]),
    [night.services, activeService],
  );

  const proposalHost = useMemo<DesignerProposalHost>(
    () => ({
      initial: {
        shots: night.shots,
        services: initialServices,
      },
      tierKey: activeTier,
      onShotsChange: (shots) => setNight({ shots }),
      onClose: () => {
        setScreen("calc");
        window.scrollTo(0, 0);
      },
      onSave: (snapshot) => {
        setNight({
          images: snapshot.shots.map((shot) => shot.image),
          services: snapshot.services,
        });

        // A drawn fixture type resolves to the product THIS package sells, so
        // the quote gets the right SKU and the crew gets its parts list. A type
        // the package doesn't sell resolves to nothing and is skipped here —
        // the designer already told the rep, and silently substituting another
        // package's product would quote hardware nobody agreed to.
        const resolution = resolveTierFixtures(pricing, catalog, activeTier);
        for (const [type, count] of Object.entries(snapshot.fixtures)) {
          const itemId = resolution[type as FixtureType]?.itemId;
          if (itemId && count > 0) setQty(itemId, count);
        }

        // A measured roofline only drives seasonal pricing, so it is scoped to
        // the christmas branch — measuring on a landscape quote must never
        // switch the service path underneath the rep.
        if (activeService === "christmas" && snapshot.rooflineFeet > 0) {
          setChristmas({ roofline_feet: String(snapshot.rooflineFeet) });
          if (!hasCategory("christmas")) toggleCategory("christmas");
        }
      },
    }),
    [
      night.shots,
      initialServices,
      activeTier,
      pricing,
      catalog,
      setNight,
      setQty,
      setChristmas,
      hasCategory,
      toggleCategory,
      activeService,
    ],
  );

  if (screen === "design") {
    // Rendered outside the `.sales-wizard` theme: the designer ships its own
    // scoped `estimator.css`, exactly as it renders in the Quotes hub.
    return (
      <LightDesigner
        workspaceId={workspaceId}
        workspaceName={brandName}
        workspaceLogoUrl={brandLogoUrl}
        proposal={proposalHost}
      />
    );
  }

  return (
    <div className={`sales-wizard ${salesWizardFontVars}`}>
      {wizard.isLoadingConfig || wizard.isLoadingQuote ? (
        <div className="screen active" aria-live="polite" aria-busy="true">
          <div className="present-body">
            <div className="wizard-review-intro">
              {wizard.isLoadingQuote ? "Loading saved quote…" : "Loading pricing…"}
            </div>
          </div>
        </div>
      ) : wizard.quoteLoadError ? (
        <div className="screen active" role="alert">
          <div className="present-body">
            <div className="wizard-review-intro">
              This quote could not be reopened. It may have been removed, or it may not be a
              sales-wizard quote.
            </div>
            <button type="button" className="btn-back" onClick={wizard.reloadQuote}>
              Retry loading quote
            </button>
          </div>
        </div>
      ) : wizard.configError ? (
        <div className="screen active" role="alert">
          <div className="present-body">
            <div className="wizard-review-intro">
              Could not load the pricing configuration for this workspace. Check Settings → Pricing,
              then reload.
            </div>
          </div>
        </div>
      ) : !hasSellablePackage ? (
        <div className="screen active" role="region" aria-label="Price Book setup required">
          <PageEmptyState
            className="min-h-screen"
            icon={<BookOpen className="size-9" />}
            title="Set up your Price Book before building a quote"
            description="Landscape Design Packages need at least one active, priced line item. Add or restore package items in Settings → Price Book, then return here."
            action={
              <Button asChild>
                <Link href="/catalog">Set up Price Book</Link>
              </Button>
            }
          />
        </div>
      ) : (
        <CalculatorScreen
          wizard={wizard}
          brandName={brandName}
          onOpenNight={() => show("design")}
        />
      )}
    </div>
  );
}
