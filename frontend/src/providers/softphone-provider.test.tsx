import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SoftphoneProvider, useSoftphone } from "./softphone-provider";

const mocks = vi.hoisted(() => ({
  getWebRTCToken: vi.fn(),
  initiate: vi.fn(),
  hangup: vi.fn(),
}));

vi.mock("@/lib/api/calls", () => ({ callsApi: mocks }));
vi.mock("@/providers/auth-provider", () => ({ useAuth: () => ({ user: { id: 1 } }) }));
vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({ currentWorkspaceId: "workspace-1" }),
}));
vi.mock("@telnyx/webrtc", () => ({
  TelnyxRTC: class {
    handlers = new Map<string, () => void>();
    remoteElement: HTMLAudioElement | null = null;

    on(event: string, handler: () => void) {
      this.handlers.set(event, handler);
    }

    off(event: string) {
      this.handlers.delete(event);
    }

    async connect() {
      this.handlers.get("telnyx.ready")?.();
    }

    async disconnect() {}
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <SoftphoneProvider>{children}</SoftphoneProvider>
    </QueryClientProvider>
  );
}

describe("SoftphoneProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getWebRTCToken.mockResolvedValue({ token: "short-lived-token", expires_at: 1 });
    mocks.hangup.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn() },
    });
  });

  it("hangs up the backend call when the operator cancels while initiation is pending", async () => {
    const initiation = deferred<{ id: string }>();
    mocks.initiate.mockReturnValue(initiation.promise);
    const { result } = renderHook(() => useSoftphone(), { wrapper });

    let startPromise!: Promise<void>;
    act(() => {
      startPromise = result.current.startCall({
        workspaceId: "workspace-1",
        contactName: "Alex Customer",
        toNumber: "+15551234567",
        fromPhoneNumber: "+15557654321",
      });
    });
    await waitFor(() => expect(result.current.phase).toBe("waiting"));

    await act(async () => {
      await result.current.hangup();
    });
    initiation.resolve({ id: "call-record-1" });
    await act(async () => {
      await startPromise;
    });

    expect(mocks.hangup).toHaveBeenCalledWith("workspace-1", "call-record-1");
    expect(result.current.phase).toBe("ended");
  });
});
