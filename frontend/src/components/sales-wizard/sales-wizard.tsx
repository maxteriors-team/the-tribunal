"use client";

/**
 * Sales Wizard root — hosts the three screens (calculator, presentation,
 * night preview) inside the scoped `.sales-wizard` dark/gold theme. All state
 * lives in `useSalesWizard`, which mirrors the selection to the backend for
 * authoritative pricing.
 */
import { useState } from "react";

import { CalculatorScreen } from "./calculator-screen";
import { salesWizardFontVars } from "./fonts";
import { NightPreviewScreen } from "./night-preview-screen";
import { PresentationScreen } from "./presentation-screen";
import { useSalesWizard } from "./use-sales-wizard";
import "./theme.css";

type Screen = "calc" | "present" | "night";

interface SalesWizardProps {
  workspaceId: string;
  brandName: string;
}

export function SalesWizard({ workspaceId, brandName }: SalesWizardProps) {
  const wizard = useSalesWizard(workspaceId);
  const [screen, setScreen] = useState<Screen>("calc");

  const show = (next: Screen) => {
    setScreen(next);
    window.scrollTo(0, 0);
  };

  return (
    <div className={`sales-wizard ${salesWizardFontVars}`}>
      {wizard.isLoadingConfig ? (
        <div className="screen active">
          <div className="present-body">
            <div className="wizard-review-intro">Loading pricing…</div>
          </div>
        </div>
      ) : wizard.configError ? (
        <div className="screen active">
          <div className="present-body">
            <div className="wizard-review-intro">
              Could not load the pricing configuration for this workspace.
              Check Settings → Pricing, then reload.
            </div>
          </div>
        </div>
      ) : screen === "calc" ? (
        <CalculatorScreen
          wizard={wizard}
          brandName={brandName}
          onPresent={() => show("present")}
          onOpenNight={() => show("night")}
        />
      ) : screen === "present" ? (
        <PresentationScreen
          wizard={wizard}
          brandName={brandName}
          onBack={() => show("calc")}
        />
      ) : (
        <NightPreviewScreen wizard={wizard} onClose={() => show("calc")} />
      )}
    </div>
  );
}
