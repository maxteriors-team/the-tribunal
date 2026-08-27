"use client";

import { Sparkles } from "lucide-react";
import Image from "next/image";
import { useState } from "react";

interface LandscapeClientPreviewProps {
  projectName: string;
  contactName?: string;
  mockupImage: string | null;
  aiImage: string | null;
  fixtureCount: number;
  bistroRunCount: number;
  packageName: string | null;
  priceLabel: string | null;
  aiRenderDisabledReason: string | null;
  onAIRender: () => void;
}

export function LandscapeClientPreview({
  projectName,
  contactName,
  mockupImage,
  aiImage,
  fixtureCount,
  bistroRunCount,
  packageName,
  priceLabel,
  aiRenderDisabledReason,
  onAIRender,
}: LandscapeClientPreviewProps) {
  const [showMockup, setShowMockup] = useState(false);
  const showingAI = Boolean(aiImage) && !showMockup;
  const image = showingAI ? aiImage : mockupImage;

  return (
    <section className="ll-client-preview" aria-labelledby="ll-client-preview-title">
      <div className="ll-client-preview-visual">
        {image ? (
          <Image
            src={image}
            width={1200}
            height={800}
            unoptimized
            alt={
              showingAI
                ? `AI-generated lighting concept for ${projectName}`
                : `Lighting plan mockup for ${projectName}`
            }
          />
        ) : (
          <div className="ll-client-preview-empty">
            Add an aerial and place fixtures to create the client preview.
          </div>
        )}
        <span className="ll-client-preview-label">
          {showingAI ? "AI lighting concept" : "Lighting plan mockup"}
        </span>
        {aiImage && mockupImage ? (
          <div className="ll-client-preview-toggle" role="group" aria-label="Preview image">
            <button
              type="button"
              className={!showMockup ? "active" : ""}
              aria-pressed={!showMockup}
              onClick={() => setShowMockup(false)}
            >
              AI render
            </button>
            <button
              type="button"
              className={showMockup ? "active" : ""}
              aria-pressed={showMockup}
              onClick={() => setShowMockup(true)}
            >
              Mockup
            </button>
          </div>
        ) : null}
      </div>

      <div className="ll-client-preview-copy">
        <p className="ll-client-preview-kicker">Client preview</p>
        <h3 id="ll-client-preview-title">{projectName}</h3>
        <p>
          {contactName
            ? `A presentation-ready view of ${contactName}’s proposed nighttime lighting.`
            : "A presentation-ready view of the proposed nighttime lighting."}
        </p>
        <dl>
          <div>
            <dt>Lighting plan</dt>
            <dd>
              {fixtureCount} {fixtureCount === 1 ? "fixture" : "fixtures"}
              {bistroRunCount
                ? ` + ${bistroRunCount} bistro ${bistroRunCount === 1 ? "run" : "runs"}`
                : ""}
            </dd>
          </div>
          <div>
            <dt>Selected package</dt>
            <dd>{packageName ?? "Choose a package below"}</dd>
          </div>
          <div>
            <dt>Project total</dt>
            <dd>{priceLabel ?? "Pricing updates below"}</dd>
          </div>
        </dl>
        <button
          type="button"
          className="est-btn primary ll-client-render-button"
          disabled={Boolean(aiRenderDisabledReason)}
          title={aiRenderDisabledReason ?? undefined}
          onClick={onAIRender}
        >
          <Sparkles aria-hidden="true" />
          Make this look real
        </button>
        <small>
          Creates one AI concept from the active mockup using the workspace OpenAI account.
        </small>
        {showingAI ? (
          <p className="ll-client-preview-disclosure">
            AI-generated concept. Confirm fixture placement and brightness before sharing.
          </p>
        ) : null}
      </div>
    </section>
  );
}
