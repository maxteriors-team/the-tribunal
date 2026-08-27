"use client";

import { Download, Loader2, Printer, RefreshCw } from "lucide-react";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useJobInstallationPlan } from "@/hooks/useJobs";
import type { JobInstallationPlan } from "@/lib/api/jobs";
import { designScale } from "@/lib/estimator/design";
import { loadImage } from "@/lib/estimator/photo";
import { drawScene } from "@/lib/estimator/render";
import type { Design, PhotoInfo, Product, RenderStyle } from "@/lib/estimator/types";

type Plan = JobInstallationPlan;

function proposalStatusLabel(status: Plan["proposal_status"]): string | null {
  if (status === "approved") return "Proposal accepted";
  if (status === "sent") return "Awaiting client acceptance";
  if (status === "declined") return "Proposal declined";
  if (status === "expired") return "Proposal expired";
  if (status === "draft") return "Proposal draft";
  return null;
}

function paymentStatusLabel(status: Plan["payment_status"]): string | null {
  if (status === "paid") return "Customer payment received";
  if (status === "pending") return "Customer payment pending";
  if (status === "not_required") return "No upfront payment required";
  return null;
}

const STYLE_BY_PRODUCT: Record<string, RenderStyle> = {
  uplight: "uplight",
  ingrade: "ingrade",
  pathlight: "pathlight",
  downlight: "downlight",
  walllight: "walllight",
  underwater: "underwater",
  transformer: "transformer",
  wire: "wire",
};

function productsFor(design: Design): Product[] {
  const ids = new Set([
    ...design.items.map((item) => item.productId),
    ...design.runs.map((run) => run.productId),
  ]);
  return [...ids].map((id) => {
    const suffix = id.replace(/^fixture-/, "");
    const style = STYLE_BY_PRODUCT[suffix] ?? (suffix.includes("wire") ? "wire" : "uplight");
    return {
      id,
      name: suffix,
      category: "landscape",
      kind: style === "wire" ? "linear" : "each",
      price: 0,
      style,
      colors: ["#ffd98a"],
      spacingIn: 0,
      sizeFt: 2,
      target: { field: "landscape", fixtureType: "uplight" },
    } as Product;
  });
}

interface InstallationPlanPanelProps {
  workspaceId: string;
  jobId: string;
}

/** Private, read-only selected-sheet renderer. It never requests the full project. */
export function InstallationPlanPanel({ workspaceId, jobId }: InstallationPlanPanelProps) {
  const query = useJobInstallationPlan(workspaceId, jobId);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    const plan = query.data;
    const canvas = canvasRef.current;
    if (!plan || !canvas) return;

    let cancelled = false;
    const photo = plan.photo as unknown as PhotoInfo;
    const design = plan.design as unknown as Design;
    void loadImage(photo.dataUrl)
      .then((image) => {
        if (cancelled) return;
        canvas.width = photo.width;
        canvas.height = photo.height;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas is unavailable");
        const productById = new Map(productsFor(design).map((product) => [product.id, product]));
        const scale = designScale(design, photo.width);
        drawScene(context, image, design, productById, scale.pxPerFt, {
          viewScale: 1,
          dusk: plan.dusk,
          showChrome: false,
        });
      })
      .then(
        () => {
          if (!cancelled) setRenderError(null);
        },
        () => {
          if (!cancelled) setRenderError("The selected sheet could not be rendered.");
        },
      );

    return () => {
      cancelled = true;
    };
  }, [query.data]);

  if (query.isPending) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading installation plan…
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="space-y-3 rounded-lg border border-dashed p-4">
        <p className="text-sm text-muted-foreground">
          No installation plan is available for this assignment.
        </p>
        <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
          <RefreshCw /> Retry
        </Button>
      </div>
    );
  }
  const plan = query.data;
  if (!plan) return null;
  const proposalLabel = proposalStatusLabel(plan.proposal_status);
  const paymentLabel = paymentStatusLabel(plan.payment_status);
  const proposalPreview =
    plan.proposal_preview_image &&
    /^data:image\/(?:jpeg|png|webp);base64,/.test(plan.proposal_preview_image)
      ? plan.proposal_preview_image
      : null;

  const download = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const anchor = document.createElement("a");
    anchor.download = `${plan.project_name}-${plan.selected_shot_id}.png`;
    anchor.href = canvas.toDataURL("image/png");
    anchor.click();
  };

  return (
    <section className="space-y-3" aria-label="Installation plan">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-medium">
            {plan.drawing_title || plan.sheet_label || "Installation plan"}
          </h3>
          <p className="text-xs text-muted-foreground">
            {plan.drawing_number ? `${plan.drawing_number} · ` : ""}
            {plan.project_name} · v{plan.project_version}
          </p>
        </div>
        <div className="flex gap-2 print:hidden">
          <Button size="sm" variant="outline" onClick={() => window.print()}>
            <Printer /> Print
          </Button>
          <Button size="sm" variant="outline" onClick={download}>
            <Download /> Download PNG
          </Button>
        </div>
      </div>
      {proposalPreview || proposalLabel || paymentLabel ? (
        <section
          className="space-y-3 rounded-lg border bg-muted/30 p-3"
          aria-label="Customer proposal status"
        >
          <div>
            <h4 className="text-sm font-semibold">Customer proposal</h4>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {proposalLabel ? (
                <span className="rounded-full border bg-background px-2 py-1">
                  {proposalLabel}
                </span>
              ) : null}
              {paymentLabel ? (
                <span className="rounded-full border bg-background px-2 py-1">
                  {paymentLabel}
                </span>
              ) : null}
            </div>
          </div>
          {proposalPreview ? (
            <figure>
              <Image
                src={proposalPreview}
                alt={plan.proposal_preview_caption || "Customer permanent-lighting preview"}
                width={1280}
                height={720}
                sizes="(max-width: 768px) 100vw, 720px"
                className="max-h-80 h-auto w-full rounded-md border bg-black/5 object-contain"
                unoptimized
              />
              {plan.proposal_preview_caption ? (
                <figcaption className="mt-1 text-xs text-muted-foreground">
                  {plan.proposal_preview_caption}
                </figcaption>
              ) : null}
            </figure>
          ) : null}
        </section>
      ) : null}
      <div className="overflow-hidden rounded-lg border bg-black/5">
        <canvas
          ref={canvasRef}
          className="h-auto w-full"
          aria-label="Selected installation drawing"
        />
      </div>
      {renderError ? <p className="text-sm text-destructive">{renderError}</p> : null}
      {plan.precon_field_brief ? (
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs font-semibold uppercase text-muted-foreground">Field brief</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{plan.precon_field_brief}</p>
        </div>
      ) : null}
      {plan.fixture_schedule?.length ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Fixture schedule
          </p>
          <ul className="grid gap-1 text-sm">
            {plan.fixture_schedule.map((fixture, index) => (
              <li key={String(fixture.item_id ?? index)} className="rounded border px-2 py-1">
                #{String(fixture.number ?? index + 1)} ·{" "}
                {String(fixture.catalog_sku ?? fixture.product_id ?? "Fixture")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
