"use client";

/**
 * Step 3 — Sales Story: the in-home slideshow (ported verbatim from the
 * uploaded wizard). Slide 5's package row shows the live cash/check totals
 * from the server preview document.
 */
import { useState } from "react";

import { fmt, type UseSalesWizardReturn } from "./use-sales-wizard";

const SLIDE_COUNT = 5;

interface StoryStepProps {
  wizard: UseSalesWizardReturn;
}

export function StoryStep({ wizard }: StoryStepProps) {
  const [slide, setSlide] = useState(0);
  const { pricing, document } = wizard;

  const order = pricing?.tier_order?.length
    ? pricing.tier_order
    : (pricing?.tiers ?? []).map((t) => t.key);

  const show = (index: number) =>
    setSlide(Math.max(0, Math.min(index, SLIDE_COUNT - 1)));

  return (
    <div className="sales-story-deck" aria-label="Sales story slideshow">
      <div className={`sales-story-slide${slide === 0 ? " active" : ""}`}>
        <div className="sales-story-kicker">01 / Set the frame</div>
        <div className="sales-story-title">
          Tonight is about <em>vision</em>, not fixtures.
        </div>
        <div className="sales-story-body">
          Top closers take control early. Tell the homeowner exactly what will
          happen, then lower pressure by saying the goal is to decide whether
          the design feels right.
        </div>
        <div className="sales-story-grid">
          <div className="sales-story-card">
            <div className="sales-story-card-label">Do</div>
            <div className="sales-story-card-text">
              Confirm their goals, budget comfort, and decision process before
              showing numbers.
            </div>
          </div>
          <div className="sales-story-card">
            <div className="sales-story-card-label">Avoid</div>
            <div className="sales-story-card-text">
              Jumping straight into line items. That makes you a commodity
              instead of the designer.
            </div>
          </div>
        </div>
        <div className="sales-story-script">
          <strong>Say this</strong>
          &ldquo;I&rsquo;ll walk you through what I saw, how I&rsquo;d light
          the home, and three ways to do it. If one feels right, we can reserve
          the install window today.&rdquo;
        </div>
      </div>

      <div className={`sales-story-slide${slide === 1 ? " active" : ""}`}>
        <div className="sales-story-kicker">02 / Diagnose</div>
        <div className="sales-story-title">
          Your home disappears after dark. <em>We reveal it.</em>
        </div>
        <div className="sales-story-body">
          Create the gap between what they have now and what they want: curb
          appeal, safer walkways, outdoor living, and a house that feels
          finished at night.
        </div>
        <div className="sales-story-grid">
          <div className="sales-story-card">
            <div className="sales-story-card-label">Ask</div>
            <div className="sales-story-card-text">
              &ldquo;When you pull in at night, what do you wish stood out
              more?&rdquo;
            </div>
          </div>
          <div className="sales-story-card">
            <div className="sales-story-card-label">Mirror back</div>
            <div className="sales-story-card-text">
              Repeat their words: entry, trees, architecture, patio, safety,
              entertaining.
            </div>
          </div>
        </div>
        <div className="sales-story-script">
          <strong>Say this</strong>
          &ldquo;The goal isn&rsquo;t more light. The goal is putting light
          where it creates emotion, safety, and depth.&rdquo;
        </div>
      </div>

      <div className={`sales-story-slide${slide === 2 ? " active" : ""}`}>
        <div className="sales-story-kicker">03 / Teach the design</div>
        <div className="sales-story-title">
          Great lighting is <em>layered</em>.
        </div>
        <div className="sales-story-body">
          Explain your system like a professional: focal points first, paths
          second, balance third. This makes your recommendation feel
          engineered, not guessed.
        </div>
        <div className="sales-story-grid">
          <div className="sales-story-card">
            <div className="sales-story-card-label">Layer 1</div>
            <div className="sales-story-card-text">
              <strong>Architecture:</strong> peaks, columns, stone, trees, and
              focal points.
            </div>
          </div>
          <div className="sales-story-card">
            <div className="sales-story-card-label">Layer 2</div>
            <div className="sales-story-card-text">
              <strong>Experience:</strong> paths, entry flow, patio glow, and
              night aiming.
            </div>
          </div>
        </div>
        <div className="sales-story-script">
          <strong>Say this</strong>
          &ldquo;Every fixture has a job. If it doesn&rsquo;t improve the
          scene, we don&rsquo;t install it.&rdquo;
        </div>
      </div>

      <div className={`sales-story-slide${slide === 3 ? " active" : ""}`}>
        <div className="sales-story-kicker">04 / Build trust</div>
        <div className="sales-story-title">
          White glove means <em>no loose ends</em>.
        </div>
        <div className="sales-story-body">
          Top closers remove risk before price. Lead with what happens after
          they say yes: clean install, buried wire, after-dark aiming, reveal
          walkthrough, and local accountability.
        </div>
        <div className="sales-story-grid">
          <div className="sales-story-card">
            <div className="sales-story-card-label">Proof</div>
            <div className="sales-story-card-text">
              Designer-led layout, premium FX fixtures, clean property
              standards, satisfaction guarantee.
            </div>
          </div>
          <div className="sales-story-card">
            <div className="sales-story-card-label">Risk reversal</div>
            <div className="sales-story-card-text">
              &ldquo;If something isn&rsquo;t right after install, we come back
              and make it right.&rdquo;
            </div>
          </div>
        </div>
        <div className="sales-story-script">
          <strong>Say this</strong>
          &ldquo;You&rsquo;re not buying boxes in the ground. You&rsquo;re
          buying the final nighttime reveal and a company that stands behind
          it.&rdquo;
        </div>
      </div>

      <div className={`sales-story-slide${slide === 4 ? " active" : ""}`}>
        <div className="sales-story-kicker">05 / Present the choice</div>
        <div className="sales-story-title">
          Three ways to get the <em>feeling</em>.
        </div>
        <div className="sales-story-body">
          Now show Good / Better / Best as outcomes, not discounts. Anchor
          high, recommend the best fit, then make the next step simple with 0%
          APR or cash/check savings.
        </div>
        <div className="sales-story-package-row">
          {order.map((key) => {
            const view = document?.tiers.find((t) => t.key === key);
            const cfg = wizard.tierConfig(key);
            const hasValue = (view?.pricing.base ?? 0) > 0;
            return (
              <div className="sales-story-package" key={key}>
                <span>
                  {view?.name ?? cfg?.name ?? key} &middot; Cash/check
                </span>
                <strong>
                  {hasValue ? fmt(view?.pricing.cash_total) : "—"}
                </strong>
              </div>
            );
          })}
        </div>
        <div className="sales-story-script">
          <strong>Say this</strong>
          &ldquo;Based on what you told me, I&rsquo;d recommend the package
          that gives you the look without overbuilding it. If this feels
          right, the next step is picking the install window.&rdquo;
        </div>
      </div>

      <div className="sales-story-controls">
        <button
          type="button"
          className="sales-story-btn"
          onClick={() => show(slide - 1)}
        >
          Back
        </button>
        <div className="sales-story-dots" aria-label="Sales story slides">
          {Array.from({ length: SLIDE_COUNT }, (_, i) => (
            <button
              key={i}
              type="button"
              className={`sales-story-dot${i === slide ? " active" : ""}`}
              aria-label={`Slide ${i + 1}`}
              onClick={() => show(i)}
            />
          ))}
        </div>
        <button
          type="button"
          className="sales-story-btn"
          onClick={() => show(slide + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
