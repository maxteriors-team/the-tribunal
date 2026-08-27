import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LandscapeClientPreview } from "./client-preview";

const baseProps = {
  projectName: "Patio lighting",
  contactName: "Pat Lee",
  mockupImage: "data:image/jpeg;base64,MOCKUP",
  aiImage: null,
  fixtureCount: 9,
  bistroRunCount: 1,
  packageName: "Better",
  priceLabel: "$6,400.00",
  aiRenderDisabledReason: null,
  onAIRender: vi.fn(),
};

describe("LandscapeClientPreview", () => {
  it("leads with the mockup, project summary, and AI render action", () => {
    const onAIRender = vi.fn();
    render(<LandscapeClientPreview {...baseProps} onAIRender={onAIRender} />);

    expect(screen.getByRole("heading", { name: "Patio lighting" })).toBeVisible();
    expect(screen.getByAltText("Lighting plan mockup for Patio lighting")).toBeVisible();
    expect(screen.getByText("9 fixtures + 1 bistro run")).toBeVisible();
    expect(screen.getByText("$6,400.00")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Make this look real" }));
    expect(onAIRender).toHaveBeenCalledOnce();
  });

  it("compares an AI concept with the exact mockup using keyboard buttons", () => {
    render(<LandscapeClientPreview {...baseProps} aiImage="data:image/jpeg;base64,AI" />);

    expect(screen.getByAltText("AI-generated lighting concept for Patio lighting")).toHaveAttribute(
      "src",
      "data:image/jpeg;base64,AI",
    );
    expect(screen.getByText(/AI-generated concept/i)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Mockup" }));
    expect(screen.getByAltText("Lighting plan mockup for Patio lighting")).toHaveAttribute(
      "src",
      "data:image/jpeg;base64,MOCKUP",
    );
  });

  it("explains why AI rendering is unavailable", () => {
    render(
      <LandscapeClientPreview
        {...baseProps}
        aiRenderDisabledReason="Place at least one fixture before rendering."
      />,
    );

    const button = screen.getByRole("button", { name: "Make this look real" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Place at least one fixture before rendering.");
  });
});
