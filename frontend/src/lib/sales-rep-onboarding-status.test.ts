import { beforeEach, describe, expect, it } from "vitest";

import {
  hasAutoRedirectedToSalesRepOnboarding,
  hasCompletedSalesRepOnboarding,
  markAutoRedirectedToSalesRepOnboarding,
  markSalesRepOnboardingCompleted,
} from "@/lib/sales-rep-onboarding-status";

beforeEach(() => {
  localStorage.clear();
});

describe("sales rep onboarding status", () => {
  it("tracks the one-time redirect separately from completion", () => {
    expect(hasAutoRedirectedToSalesRepOnboarding(101, "workspace-a")).toBe(false);
    expect(hasCompletedSalesRepOnboarding(101, "workspace-a")).toBe(false);

    markAutoRedirectedToSalesRepOnboarding(101, "workspace-a");

    expect(hasAutoRedirectedToSalesRepOnboarding(101, "workspace-a")).toBe(true);
    expect(hasCompletedSalesRepOnboarding(101, "workspace-a")).toBe(false);

    markSalesRepOnboardingCompleted(101, "workspace-a");

    expect(hasCompletedSalesRepOnboarding(101, "workspace-a")).toBe(true);
  });

  it("scopes completion to both the user and workspace", () => {
    markSalesRepOnboardingCompleted(202, "workspace-a");

    expect(hasCompletedSalesRepOnboarding(202, "workspace-a")).toBe(true);
    expect(hasCompletedSalesRepOnboarding(202, "workspace-b")).toBe(false);
    expect(hasCompletedSalesRepOnboarding(203, "workspace-a")).toBe(false);
  });
});
