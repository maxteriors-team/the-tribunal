import { DndContext } from "@dnd-kit/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpportunityCard } from "@/components/opportunities/opportunity-card";
import type { Opportunity, PipelineStage } from "@/types";

const stage: PipelineStage = {
  id: "stage-1",
  pipeline_id: "pipeline-1",
  name: "Qualified",
  order: 0,
  probability: 40,
  stage_type: "active",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const opportunity: Opportunity = {
  id: "opportunity-1",
  workspace_id: "workspace-1",
  pipeline_id: "pipeline-1",
  stage_id: "stage-1",
  name: "Roof replacement",
  amount: 4200,
  currency: "USD",
  probability: 40,
  status: "open",
  is_active: true,
  primary_contact_id: 42,
  primary_contact: {
    id: 42,
    first_name: "Helen",
    last_name: "Vasquez",
    full_name: "Helen Vasquez",
    phone_number: "+15551234567",
    email: "helen@example.com",
    status: "qualified",
  },
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function renderCard(overrides: Partial<Opportunity> = {}) {
  const handlers = {
    onOpen: vi.fn(),
    onMove: vi.fn(),
    onCall: vi.fn(),
    onText: vi.fn(),
    onSchedule: vi.fn(),
    onRemove: vi.fn(),
  };

  render(
    <DndContext>
      <OpportunityCard
        opportunity={{ ...opportunity, ...overrides }}
        stages={[stage]}
        {...handlers}
      />
    </DndContext>,
  );

  return handlers;
}

describe("OpportunityCard", () => {
  it("opens the routed deal from the keyboard-operable card face", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderCard();

    await user.tab();
    expect(document.activeElement).toHaveTextContent("Roof replacement");
    await user.keyboard("{Enter}");

    expect(onOpen).toHaveBeenCalledWith("opportunity-1");
  });

  it("keeps call, text, and booking actions separate from opening the card", async () => {
    const user = userEvent.setup();
    const { onOpen, onCall, onText, onSchedule } = renderCard();

    await user.click(screen.getByRole("button", { name: "Call Helen Vasquez" }));
    await user.click(screen.getByRole("button", { name: "Text Helen Vasquez" }));
    await user.click(
      screen.getByRole("button", { name: "Book an appointment with Helen Vasquez" }),
    );

    expect(onCall).toHaveBeenCalledWith(opportunity);
    expect(onText).toHaveBeenCalledWith(opportunity);
    expect(onSchedule).toHaveBeenCalledWith(opportunity);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("disables phone quick actions when the linked contact has no number", () => {
    renderCard({
      primary_contact: { ...opportunity.primary_contact!, phone_number: null },
    });

    expect(screen.getByRole("button", { name: /Call Helen Vasquez: no phone/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Text Helen Vasquez: no phone/ })).toBeDisabled();
  });
});
