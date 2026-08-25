import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiPutMock } = vi.hoisted(() => ({ apiPutMock: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPut: apiPutMock,
}));

import { nudgesApi } from "@/lib/api/nudges";

const workspaceId = "6aee02cf-5ea9-49bd-88bb-d6cb720579a3";

describe("nudgesApi.clearAll", () => {
  beforeEach(() => apiPutMock.mockReset());

  it("uses the workspace-scoped Clear All endpoint once", async () => {
    const result = { dismissed_count: 3 };
    apiPutMock.mockResolvedValue(result);

    await expect(nudgesApi.clearAll(workspaceId)).resolves.toBe(result);
    expect(apiPutMock).toHaveBeenCalledOnce();
    expect(apiPutMock).toHaveBeenCalledWith(`/api/v1/workspaces/${workspaceId}/nudges/clear-all`);
  });
});
