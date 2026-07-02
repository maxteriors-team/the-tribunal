"use client";

/**
 * Step 2 — Design Packages: tier tabs, fixture steppers, custom charges.
 * A direct port of the uploaded wizard's renderCalculator()/renderCharges();
 * every price shown comes from the server preview document (grossed prices).
 */
import { fmt, type UseSalesWizardReturn } from "./use-sales-wizard";

interface DesignStepProps {
  wizard: UseSalesWizardReturn;
}

export function MiniTotals({ wizard }: { wizard: UseSalesWizardReturn }) {
  const { pricing, document } = wizard;
  const order = pricing?.tier_order?.length
    ? pricing.tier_order
    : (pricing?.tiers ?? []).map((t) => t.key);
  return (
    <div className="wizard-mini-totals" aria-label="Live package totals">
      {order.map((key) => {
        const view = document?.tiers.find((t) => t.key === key);
        const cfg = wizard.tierConfig(key);
        const hasValue = (view?.pricing.base ?? 0) > 0;
        return (
          <div className="wizard-mini-total" key={key}>
            <span>{view?.name ?? cfg?.name ?? cfg?.label ?? key}</span>
            <strong>
              {hasValue ? fmt(view?.pricing.financed_total) : "—"}
            </strong>
          </div>
        );
      })}
    </div>
  );
}

export function DesignStep({ wizard }: DesignStepProps) {
  const {
    pricing,
    document,
    activeTier,
    setActiveTier,
    quantities,
    setQty,
    changeQty,
    charges,
    setCharge,
    addCharge,
    removeCharge,
  } = wizard;

  const tiers = pricing?.tiers ?? [];
  const order = pricing?.tier_order?.length
    ? pricing.tier_order
    : tiers.map((t) => t.key);
  const active = tiers.find((t) => t.key === activeTier) ?? tiers[0];

  return (
    <>
      <div className="tier-tabs">
        {order.map((key) => {
          const cfg = wizard.tierConfig(key);
          if (!cfg) return null;
          return (
            <button
              key={key}
              type="button"
              className={`tier-tab ${key}${key === active?.key ? " active" : ""}`}
              onClick={() => setActiveTier(key)}
            >
              {cfg.marker ? `${cfg.marker}\u00a0 ` : ""}
              {cfg.tab ?? cfg.label}
              <span className="tier-tab-sub">{cfg.tab_sub ?? cfg.name}</span>
            </button>
          );
        })}
      </div>

      {active ? (
        <div className="tier-panel active">
          {(active.sections ?? []).map((section, i) => {
            const subtotal = (section.item_ids ?? []).reduce((sum, id) => {
              const line = wizard.lineFor(active.key, id);
              return sum + (line?.line_total ?? 0);
            }, 0);
            return (
              <div className="fixture-section" key={`${active.key}-${i}`}>
                <div className="fixture-section-header">
                  <div className="fixture-section-title">{section.title}</div>
                  <div className="fixture-section-subtotal">
                    {subtotal > 0 ? fmt(subtotal) : "—"}
                  </div>
                </div>
                <div className="fixture-rows">
                  {(section.item_ids ?? []).map((itemId) => {
                    const line = wizard.lineFor(active.key, itemId);
                    const catalogItem = wizard.catalog?.find(
                      (c) => c.sku === itemId || c.id === itemId,
                    );
                    const qty = quantities[itemId] ?? 0;
                    const lineTotal = line?.line_total ?? 0;
                    return (
                      <div
                        className={`fix-row${qty > 0 ? " active-row" : ""}`}
                        key={itemId}
                      >
                        <div className="fix-name-wrap">
                          <div className="fix-name">
                            {line?.name ?? catalogItem?.name ?? itemId}
                          </div>
                          <div className="fix-price">
                            {line ? `${fmt(line.unit_price)} / ea` : "—"}
                          </div>
                        </div>
                        <div className="fix-controls">
                          <div className="stepper">
                            <button
                              type="button"
                              className="step-btn"
                              onClick={() => changeQty(itemId, -1)}
                            >
                              &#8722;
                            </button>
                            <input
                              className="step-val"
                              type="number"
                              min={0}
                              value={qty}
                              onChange={(e) =>
                                setQty(
                                  itemId,
                                  Number.parseInt(e.target.value, 10) || 0,
                                )
                              }
                            />
                            <button
                              type="button"
                              className="step-btn"
                              onClick={() => changeQty(itemId, 1)}
                            >
                              +
                            </button>
                          </div>
                          <div
                            className={`fix-line-total${lineTotal > 0 ? " has-value" : ""}`}
                          >
                            {lineTotal > 0 ? fmt(lineTotal) : "—"}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      <div>
        {charges.map((charge, i) => (
          <div className="additional-row" key={i}>
            <div className="additional-label">Add-on</div>
            <input
              type="text"
              className="additional-desc"
              placeholder="e.g. Core drilling, rock removal… (enter the amount you keep — fee buffer added automatically)"
              value={charge.description}
              onChange={(e) => setCharge(i, { description: e.target.value })}
            />
            <div className="additional-amount-wrap">
              <span className="dollar-sign">$</span>
              <input
                type="number"
                className="additional-amount"
                placeholder="0"
                min={0}
                value={charge.amount}
                onChange={(e) => setCharge(i, { amount: e.target.value })}
              />
            </div>
            <button
              type="button"
              className="charge-del"
              title="Remove this charge"
              onClick={() => removeCharge(i)}
            >
              &#10005;
            </button>
          </div>
        ))}
        <button type="button" className="charge-add" onClick={addCharge}>
          + Add another charge
        </button>
      </div>

      <MiniTotals wizard={wizard} />
      {document ? null : (
        <div className="wizard-review-intro" style={{ marginTop: 10 }}>
          Pricing…
        </div>
      )}
    </>
  );
}
