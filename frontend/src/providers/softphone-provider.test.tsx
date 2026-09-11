import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SoftphoneProvider, useSoftphone } from "./softphone-provider";

const mocks = vi.hoisted(() => ({
  getWebRTCToken: vi.fn(),
  initiate: vi.fn(),
  hangup: vi.fn(),
  publishPresence: vi.fn(),
  publishPresenceBeacon: vi.fn(),
}));

/** The most recent fake Telnyx client, so a test can push an inbound invite. */
const clients = vi.hoisted(() => ({ current: null as FakeTelnyxClient | null }));

interface FakeCall {
  id: string;
  direction: string;
  state: string;
  options: { remoteCallerNumber?: string };
  answer: ReturnType<typeof vi.fn>;
  hangup: ReturnType<typeof vi.fn>;
}

interface FakeTelnyxClient {
  handlers: Map<string, (payload: unknown) => void>;
  notify: (call: FakeCall) => void;
}

vi.mock("@/lib/api/calls", () => ({ callsApi: mocks }));
vi.mock("@/providers/auth-provider", () => ({ useAuth: () => ({ user: { id: 1 } }) }));
vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({ currentWorkspaceId: "workspace-1" }),
}));
vi.mock("@telnyx/webrtc", () => ({
  TelnyxRTC: class {
    handlers = new Map<string, (payload: unknown) => void>();
    remoteElement: HTMLAudioElement | null = null;

    constructor() {
      clients.current = this as unknown as FakeTelnyxClient;
    }

    on(event: string, handler: (payload: unknown) => void) {
      this.handlers.set(event, handler);
      return this;
    }

    off(event: string) {
      this.handlers.delete(event);
      return this;
    }

    async connect() {
      this.handlers.get("telnyx.ready")?.(undefined);
    }

    async disconnect() {}

    /** Deliver a callUpdate exactly as the SDK does. */
    notify(call: FakeCall) {
      this.handlers.get("telnyx.notification")?.({ type: "callUpdate", call });
    }
  },
}));

let inviteCounter = 0;

function inboundCall(overrides: Partial<FakeCall> = {}): FakeCall {
  return {
    id: `invite-${++inviteCounter}`,
    direction: "inbound",
    state: "ringing",
    options: { remoteCallerNumber: "+15551234567" },
    // The SDK's call methods are async; the provider chains .catch() on them.
    answer: vi.fn(async () => undefined),
    hangup: vi.fn(async () => undefined),
    ...overrides,
  };
}

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
    mocks.publishPresence.mockResolvedValue(undefined);
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

  it("publishes presence once the headset is registered", async () => {
    renderHook(() => useSoftphone(), { wrapper });

    await waitFor(() => expect(mocks.publishPresence).toHaveBeenCalledWith("workspace-1", true));
  });

  it("stops advertising availability when the dashboard unmounts", async () => {
    const { unmount } = renderHook(() => useSoftphone(), { wrapper });
    await waitFor(() => expect(mocks.publishPresence).toHaveBeenCalledWith("workspace-1", true));

    unmount();

    await waitFor(() => expect(mocks.publishPresence).toHaveBeenCalledWith("workspace-1", false));
  });

  it("surfaces an incoming customer call to the operator", async () => {
    const { result } = renderHook(() => useSoftphone(), { wrapper });
    await waitFor(() => expect(result.current.isRegistered).toBe(true));

    act(() => clients.current?.notify(inboundCall()));

    await waitFor(() => expect(result.current.incoming?.callerNumber).toBe("+15551234567"));
  });

  it("answers the call when the operator accepts", async () => {
    const call = inboundCall();
    const { result } = renderHook(() => useSoftphone(), { wrapper });
    await waitFor(() => expect(result.current.isRegistered).toBe(true));
    act(() => clients.current?.notify(call));
    await waitFor(() => expect(result.current.incoming).not.toBeNull());

    await act(async () => {
      await result.current.acceptIncoming();
    });

    expect(call.answer).toHaveBeenCalledOnce();
    expect(call.hangup).not.toHaveBeenCalled();
  });

  it("keeps the headset registered after declining, so the next call still rings", async () => {
    const call = inboundCall();
    const { result } = renderHook(() => useSoftphone(), { wrapper });
    await waitFor(() => expect(result.current.isRegistered).toBe(true));
    act(() => clients.current?.notify(call));
    await waitFor(() => expect(result.current.incoming).not.toBeNull());

    await act(async () => {
      await result.current.declineIncoming();
    });

    expect(call.hangup).toHaveBeenCalledOnce();
    expect(call.answer).not.toHaveBeenCalled();
    expect(result.current.incoming).toBeNull();
    // The whole point of declining rather than disconnecting.
    expect(result.current.isRegistered).toBe(true);
    expect(mocks.publishPresence).not.toHaveBeenCalledWith("workspace-1", false);
  });

  it("refuses a second invite instead of dropping the call in progress", async () => {
    const first = inboundCall();
    const second = inboundCall();
    const { result } = renderHook(() => useSoftphone(), { wrapper });
    await waitFor(() => expect(result.current.isRegistered).toBe(true));
    act(() => clients.current?.notify(first));
    await waitFor(() => expect(result.current.incoming).not.toBeNull());

    act(() => clients.current?.notify(second));

    expect(second.hangup).toHaveBeenCalledOnce();
    expect(first.hangup).not.toHaveBeenCalled();
    expect(result.current.incoming?.callerNumber).toBe("+15551234567");
  });
});
