import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  delete: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiDelete: apiMocks.delete,
  apiGet: apiMocks.get,
  apiPost: apiMocks.post,
  apiPut: apiMocks.put,
}));

vi.mock("@/lib/utils/backend-url", () => ({
  getBackendUrl: () => "https://api.example.com",
}));

import { publicReferralPartnerIntakeApi } from "@/lib/api/referral-partners";

describe("public referral-partner intake API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the direct backend without CRM cookies", async () => {
    apiMocks.get.mockResolvedValue({ name: "Bright Spark Electric" });

    await publicReferralPartnerIntakeApi.get("safe-capability");

    expect(apiMocks.get).toHaveBeenCalledWith("/api/v1/public/referral-partners/intake", {
      baseURL: "https://api.example.com",
      headers: { Authorization: "Bearer safe-capability" },
      withCredentials: false,
    });
  });
});
