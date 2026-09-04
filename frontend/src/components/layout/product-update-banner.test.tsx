import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ProductUpdateBanner } from "./product-update-banner";

const DISMISSED_KEY = "crm-announcement-permanent-customer-handoff-v2";

describe("ProductUpdateBanner", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("summarizes the update and stays closed after dismissal", () => {
    const { unmount } = render(<ProductUpdateBanner />);

    expect(screen.getByRole("status", { name: "Product update" })).toHaveTextContent(
      "Permanent-lighting projects stay connected",
    );
    expect(screen.getByRole("status", { name: "Product update" })).toHaveTextContent(
      "Save designs to a customer, send a price range, and carry the approved mockup and design into the job",
    );

    fireEvent.click(screen.getByRole("button", { name: "Dismiss product update" }));

    expect(screen.queryByRole("status", { name: "Product update" })).not.toBeInTheDocument();
    expect(window.localStorage.getItem(DISMISSED_KEY)).toBe("dismissed");

    unmount();
    render(<ProductUpdateBanner />);

    expect(screen.queryByRole("status", { name: "Product update" })).not.toBeInTheDocument();
  });
});
