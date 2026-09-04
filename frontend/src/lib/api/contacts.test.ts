import { beforeEach, describe, expect, it, vi } from "vitest";

const { getMock, putMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  putMock: vi.fn(),
}));

vi.mock("@/lib/api/_client", () => ({
  apiClient: {
    get: getMock,
    put: putMock,
  },
}));

vi.mock("@/lib/api/create-api-client", () => ({
  createApiClient: () => ({}),
}));

import { contactsApi } from "@/lib/api/contacts";

const workspaceId = "6aee02cf-5ea9-49bd-88bb-d6cb720579a3";
const contactId = 42;
const factId = "bc155b11-ccfe-4a69-a6f7-2f5604beefa9";

describe("contact AI knowledge API", () => {
  beforeEach(() => {
    getMock.mockReset();
    putMock.mockReset();
  });

  it("reads the workspace-scoped data-minimized projection", async () => {
    const response = { contact_id: contactId, generated_at: "2026-08-17T12:00:00Z" };
    getMock.mockResolvedValue(response);

    await expect(contactsApi.getAIKnowledge(workspaceId, contactId)).resolves.toBe(response);
    expect(getMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/ai-knowledge",
      { path: { workspace_id: workspaceId, contact_id: contactId } },
    );
  });

  it("sends a summary correction without touching the contact endpoint", async () => {
    putMock.mockResolvedValue({ contact_id: contactId });

    await contactsApi.updateAIMemorySummary(workspaceId, contactId, "Corrected summary");

    expect(putMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/ai-knowledge/summary",
      {
        path: { workspace_id: workspaceId, contact_id: contactId },
        body: { value: "Corrected summary" },
      },
    );
  });

  it("uses null to remove one generated fact under its exact scope", async () => {
    putMock.mockResolvedValue({ contact_id: contactId });

    await contactsApi.updateAIMemoryFact(workspaceId, contactId, factId, null);

    expect(putMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/ai-knowledge/facts/{fact_id}",
      {
        path: {
          workspace_id: workspaceId,
          contact_id: contactId,
          fact_id: factId,
        },
        body: { value: null },
      },
    );
  });
});

describe("contact timeline API", () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it("preserves synced provider provenance for conversation rendering", async () => {
    getMock.mockResolvedValue([
      {
        id: "message-1",
        type: "sms",
        timestamp: "2026-08-26T12:00:00Z",
        direction: "inbound",
        is_ai: false,
        agent_id: null,
        content: "Imported provider message",
        duration_seconds: null,
        recording_url: null,
        transcript: null,
        status: "received",
        source_provider: "legacy_import",
        external_url: "https://archive.example/conversations/abc",
        booking_outcome: null,
        signals: null,
        attachments: [],
        original_id: "message-1",
        original_type: "sms_message",
      },
    ]);

    await expect(contactsApi.getTimeline(workspaceId, contactId)).resolves.toEqual([
      expect.objectContaining({
        source_provider: "legacy_import",
        external_url: "https://archive.example/conversations/abc",
      }),
    ]);
  });
});
