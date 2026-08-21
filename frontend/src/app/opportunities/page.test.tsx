import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import OpportunitiesRoute from "@/app/opportunities/page";

vi.mock("@/components/layout/app-sidebar", () => ({
  AppSidebar: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/opportunities/opportunities-board", () => ({
  OpportunitiesBoard: () => <div data-testid="opportunities-board" />,
}));

describe("OpportunitiesRoute", () => {
  it("lets the app shell scroll when controls need more vertical room", () => {
    render(<OpportunitiesRoute />);

    const page = screen.getByRole("heading", { name: "Opportunities" }).parentElement?.parentElement;
    const boardContainer = screen.getByTestId("opportunities-board").parentElement;

    expect(page).toHaveClass("h-full", "min-h-full");
    expect(page).not.toHaveClass("overflow-hidden");
    expect(boardContainer).toHaveClass("min-h-[20rem]", "flex-1");
  });
});
