"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { Call as TelnyxCall, INotification, TelnyxRTC } from "@telnyx/webrtc";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { IncomingCallBanner } from "@/components/calls/incoming-call-banner";
import { SoftphoneBar } from "@/components/calls/softphone-bar";
import { useCapabilities } from "@/hooks/useCapabilities";
import { callsApi } from "@/lib/api/calls";
import { queryKeys } from "@/lib/query-keys";
import { formatPhoneNumber } from "@/lib/utils/phone";
import { useAuth } from "@/providers/auth-provider";
import { useWorkspace } from "@/providers/workspace-provider";

export type SoftphonePhase =
  | "idle"
  | "preparing"
  | "waiting"
  | "ringing"
  | "active"
  | "ended"
  | "error";

interface BrowserCallRequest {
  workspaceId: string;
  contactName: string;
  toNumber: string;
  fromPhoneNumber: string;
}

/** A customer invite that is ringing this browser and has not been decided yet. */
export interface IncomingCall {
  /** Caller's number as Telnyx delivered it (E.164); formatted at the edge. */
  callerNumber: string;
  /** True once the operator accepted and the media handshake is in flight. */
  isConnecting: boolean;
}

interface SoftphoneState {
  phase: SoftphonePhase;
  contactName: string;
  isMuted: boolean;
  startedAt: number | null;
  error: string | null;
}

interface SoftphoneContextValue extends SoftphoneState {
  /** The Telnyx client is logged in and this browser can be rung. */
  isRegistered: boolean;
  incoming: IncomingCall | null;
  startCall: (request: BrowserCallRequest) => Promise<void>;
  answer: () => Promise<void>;
  acceptIncoming: () => Promise<void>;
  declineIncoming: () => Promise<void>;
  toggleMute: () => Promise<void>;
  hangup: () => Promise<void>;
  dismiss: () => void;
}

const INITIAL_STATE: SoftphoneState = {
  phase: "idle",
  contactName: "",
  isMuted: false,
  startedAt: null,
  error: null,
};

/** Backend presence TTL is 75s, so two beats fit inside it before it lapses. */
const PRESENCE_INTERVAL_MS = 30_000;
const RECONNECT_BASE_DELAY_MS = 2_000;
const RECONNECT_MAX_DELAY_MS = 60_000;

const SoftphoneContext = createContext<SoftphoneContextValue | null>(null);

function isTerminalCallState(state: string): boolean {
  return state === "hangup" || state === "destroy" || state === "purge";
}

/** For an inbound leg Telnyx puts the customer in `remoteCaller*`. */
function callerNumberOf(call: TelnyxCall): string {
  return call.options.remoteCallerNumber || call.options.remoteCallerName || "";
}

export function SoftphoneProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { currentWorkspaceId } = useWorkspace();
  // Minting a Telnyx credential is a `comms:send` action on the backend, and a
  // field technician has no calling surface at all. Registering them would only
  // earn 403s on every page and hand out voice credentials nobody can use.
  const { can } = useCapabilities();
  const canUseSoftphone = can("comms:send");
  const [state, setState] = useState<SoftphoneState>(INITIAL_STATE);
  const [incoming, setIncoming] = useState<IncomingCall | null>(null);
  const [isRegistered, setIsRegistered] = useState(false);
  const stateRef = useRef(state);
  const clientRef = useRef<TelnyxRTC | null>(null);
  const callRef = useRef<TelnyxCall | null>(null);
  /** The un-answered inbound invite, if any. Never the same call as `callRef`. */
  const incomingCallRef = useRef<TelnyxCall | null>(null);
  /** The live call arrived from a customer, so its end returns us to idle. */
  const inboundCallRef = useRef(false);
  const callRecordIdRef = useRef<string | null>(null);
  const workspaceIdRef = useRef<string | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const cancelRequestedRef = useRef(false);
  /** Workspace whose client is logged in; set only once Telnyx reports ready. */
  const registeredWorkspaceRef = useRef<string | null>(null);
  const connectPromiseRef = useRef<Promise<void> | null>(null);
  const presenceTimerRef = useRef<number | null>(null);
  /** Set by the registration effect so a dropped socket can ask for a retry. */
  const reconnectRef = useRef<(() => void) | null>(null);

  const updateState = useCallback((patch: Partial<SoftphoneState>) => {
    setState((current) => {
      const next = { ...current, ...patch };
      stateRef.current = next;
      return next;
    });
  }, []);

  const resetState = useCallback(() => {
    stateRef.current = INITIAL_STATE;
    setState(INITIAL_STATE);
  }, []);

  const stopPresence = useCallback(() => {
    if (presenceTimerRef.current !== null) {
      window.clearInterval(presenceTimerRef.current);
      presenceTimerRef.current = null;
    }
  }, []);

  const startPresence = useCallback(
    (workspaceId: string) => {
      stopPresence();
      // Failures are swallowed on purpose: the server TTL spans two beats, so
      // one flaky request must not pull the operator out of the ring group.
      const publish = () =>
        void callsApi.publishPresence(workspaceId, true).catch(() => undefined);
      publish();
      presenceTimerRef.current = window.setInterval(publish, PRESENCE_INTERVAL_MS);
    },
    [stopPresence],
  );

  /**
   * Drop the current call/invite — mic included — while staying registered.
   *
   * Registration outlives individual calls now, so ending one must never take
   * the browser out of the ring group.
   */
  const releaseCall = useCallback(() => {
    callRef.current = null;
    incomingCallRef.current = null;
    inboundCallRef.current = false;
    callRecordIdRef.current = null;
    workspaceIdRef.current = null;
    // The microphone is held for the duration of a call and never at rest.
    localStreamRef.current?.getTracks().forEach((track) => track.stop());
    localStreamRef.current = null;
    setIncoming(null);
  }, []);

  /** Full teardown: logout, workspace switch, unmount, or a dead socket. */
  const disconnectClient = useCallback(() => {
    const client = clientRef.current;
    const registeredWorkspaceId = registeredWorkspaceRef.current;
    clientRef.current = null;
    connectPromiseRef.current = null;
    registeredWorkspaceRef.current = null;
    releaseCall();
    stopPresence();
    setIsRegistered(false);
    if (registeredWorkspaceId) {
      void callsApi.publishPresence(registeredWorkspaceId, false).catch(() => undefined);
    }
    if (client) void client.disconnect().catch(() => undefined);
  }, [releaseCall, stopPresence]);

  const dismiss = useCallback(() => {
    releaseCall();
    resetState();
  }, [releaseCall, resetState]);

  const handleNotification = useCallback(
    (notification: INotification) => {
      if (notification.type !== "callUpdate" || !notification.call) return;

      const call = notification.call;
      const callState = String(call.state).toLowerCase();
      const isInbound = String(call.direction).toLowerCase() === "inbound";
      const pendingInvite = incomingCallRef.current;

      // A customer ringing this browser. Handled apart from the outbound flow,
      // where startCall() already owns the call object.
      if (isInbound && call.id !== callRef.current?.id && call.id !== pendingInvite?.id) {
        if (isTerminalCallState(callState)) return;
        if (callRef.current || pendingInvite) {
          // Already talking, or already deciding on an earlier invite. Reject
          // this leg so the backend can route the caller somewhere else
          // instead of ringing a busy operator forever.
          void call.hangup().catch(() => undefined);
          return;
        }
        incomingCallRef.current = call;
        setIncoming({ callerNumber: callerNumberOf(call), isConnecting: false });
        return;
      }

      // Updates for an invite the operator has not accepted yet.
      if (pendingInvite && call.id === pendingInvite.id) {
        if (isTerminalCallState(callState)) {
          // Caller gave up (or we declined): back to registered and idle.
          releaseCall();
          resetState();
        }
        return;
      }

      if (!callRef.current) callRef.current = call;
      if (callRef.current.id !== call.id) return;

      if (callState === "active") {
        setIncoming(null);
        updateState({
          phase: "active",
          startedAt: stateRef.current.startedAt ?? Date.now(),
          error: null,
        });
      } else if (isTerminalCallState(callState)) {
        const wasInbound = inboundCallRef.current;
        const workspaceId = workspaceIdRef.current ?? registeredWorkspaceRef.current;
        releaseCall();
        if (wasInbound) {
          // An answered customer call has no "Call ended" card to dismiss —
          // the operator goes straight back to waiting for the next one.
          resetState();
          if (workspaceId) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.calls.all(workspaceId) });
          }
        } else {
          updateState({ phase: "ended", isMuted: false });
        }
      } else if (stateRef.current.phase === "waiting") {
        updateState({ phase: "ringing" });
      }
    },
    [queryClient, releaseCall, resetState, updateState],
  );

  const connect = useCallback(
    async (workspaceId: string): Promise<void> => {
      const { token } = await callsApi.getWebRTCToken(workspaceId);
      const { TelnyxRTC: TelnyxRTCClient } = await import("@telnyx/webrtc");
      const client = new TelnyxRTCClient({ login_token: token });
      if (remoteAudioRef.current) client.remoteElement = remoteAudioRef.current;
      clientRef.current = client;
      client.on("telnyx.notification", handleNotification);

      // The socket closing (or the JWT lapsing behind it) un-registers this
      // browser silently, so hand the lifecycle effect a fresh start rather
      // than sitting there looking available.
      const onDropped = () => {
        if (clientRef.current !== client) return;
        clientRef.current = null;
        connectPromiseRef.current = null;
        registeredWorkspaceRef.current = null;
        stopPresence();
        setIsRegistered(false);
        // A pending invite dies with the socket it arrived on.
        if (incomingCallRef.current) releaseCall();
        reconnectRef.current?.();
      };
      client.on("telnyx.socket.close", onDropped);

      try {
        await new Promise<void>((resolve, reject) => {
          const timeout = window.setTimeout(() => {
            reject(new Error("Headset connection timed out. Check your network and retry."));
          }, 15_000);
          const onReady = () => {
            window.clearTimeout(timeout);
            client.off("telnyx.error", onError);
            resolve();
          };
          const onError = () => {
            window.clearTimeout(timeout);
            client.off("telnyx.ready", onReady);
            reject(new Error("The headset could not connect to Telnyx."));
          };
          client.on("telnyx.ready", onReady);
          client.on("telnyx.error", onError);
          void client.connect().catch(onError);
        });
      } catch (error) {
        if (clientRef.current === client) clientRef.current = null;
        void client.disconnect().catch(() => undefined);
        throw error;
      }
      registeredWorkspaceRef.current = workspaceId;
    },
    [handleNotification, releaseCall, stopPresence],
  );

  /**
   * Reuse the registered client when there is one.
   *
   * Placing a call no longer tears the client down and builds a new one: the
   * operator is already logged in, and re-logging in mid-flow would drop them
   * out of the ring group for the duration.
   */
  const ensureConnected = useCallback(
    async (workspaceId: string): Promise<void> => {
      if (registeredWorkspaceRef.current && registeredWorkspaceRef.current !== workspaceId) {
        disconnectClient();
      }
      if (clientRef.current && registeredWorkspaceRef.current === workspaceId) return;
      connectPromiseRef.current ??= connect(workspaceId).finally(() => {
        connectPromiseRef.current = null;
      });
      await connectPromiseRef.current;
    },
    [connect, disconnectClient],
  );

  const startCall = useCallback(
    async (request: BrowserCallRequest) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Browser calling needs desktop Chrome and microphone access.");
      }
      if (
        !["idle", "ended", "error"].includes(stateRef.current.phase) ||
        callRef.current ||
        incomingCallRef.current
      ) {
        throw new Error("Finish the current browser call before starting another.");
      }

      cancelRequestedRef.current = false;
      releaseCall();
      updateState({
        phase: "preparing",
        contactName: request.contactName,
        isMuted: false,
        startedAt: null,
        error: null,
      });

      try {
        workspaceIdRef.current = request.workspaceId;
        await ensureConnected(request.workspaceId);
        updateState({ phase: "waiting" });
        const callRecord = await callsApi.initiate(request.workspaceId, {
          to_number: request.toNumber,
          from_phone_number: request.fromPhoneNumber,
          contact_phone: request.toNumber,
          mode: "browser",
        });
        callRecordIdRef.current = callRecord.id;
        if (cancelRequestedRef.current) {
          await callsApi.hangup(request.workspaceId, callRecord.id).catch(() => undefined);
          releaseCall();
          updateState({ phase: "ended", isMuted: false });
          return;
        }
        void queryClient.invalidateQueries({
          queryKey: queryKeys.calls.all(request.workspaceId),
        });
      } catch (error) {
        releaseCall();
        if (cancelRequestedRef.current) {
          updateState({ phase: "ended", isMuted: false });
          return;
        }
        const message = error instanceof Error ? error.message : "Browser calling failed.";
        updateState({ phase: "error", error: message });
        throw error;
      }
    },
    [ensureConnected, queryClient, releaseCall, updateState],
  );

  const answer = useCallback(async () => {
    const call = callRef.current;
    if (!call) return;
    try {
      const localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
        },
        video: false,
      });
      localStreamRef.current = localStream;
      call.options.localStream = localStream;
      if (remoteAudioRef.current) call.options.remoteElement = remoteAudioRef.current;
      await call.answer();
    } catch {
      await call.hangup().catch(() => undefined);
      releaseCall();
      updateState({ phase: "error", error: "Microphone access failed. Check Chrome permissions." });
    }
  }, [releaseCall, updateState]);

  /**
   * Take the ringing customer call.
   *
   * The invite is promoted to the active call first so the existing answer()
   * path — microphone acquisition plus `call.answer()` — is reused verbatim.
   */
  const acceptIncoming = useCallback(async () => {
    const call = incomingCallRef.current;
    if (!call) return;
    incomingCallRef.current = null;
    callRef.current = call;
    inboundCallRef.current = true;
    setIncoming({ callerNumber: callerNumberOf(call), isConnecting: true });
    updateState({
      contactName: formatPhoneNumber(callerNumberOf(call)) || "Incoming call",
      isMuted: false,
      startedAt: null,
      error: null,
    });
    await answer();
  }, [answer, updateState]);

  /**
   * Refuse this call only. The client stays logged in, so the next customer
   * still rings this browser.
   */
  const declineIncoming = useCallback(async () => {
    const call = incomingCallRef.current ?? (inboundCallRef.current ? callRef.current : null);
    if (!call) return;
    releaseCall();
    resetState();
    await call.hangup().catch(() => undefined);
  }, [releaseCall, resetState]);

  const toggleMute = useCallback(async () => {
    const call = callRef.current;
    if (!call || stateRef.current.phase !== "active") return;
    if (stateRef.current.isMuted) {
      await call.unmuteAudio();
      updateState({ isMuted: false });
    } else {
      await call.muteAudio();
      updateState({ isMuted: true });
    }
  }, [updateState]);

  const hangup = useCallback(async () => {
    // Also cancels the pre-call token window before callRef has been assigned.
    cancelRequestedRef.current = true;
    const workspaceId = workspaceIdRef.current;
    const callRecordId = callRecordIdRef.current;
    const call = callRef.current ?? incomingCallRef.current;
    const wasInbound = inboundCallRef.current || incomingCallRef.current !== null;
    await Promise.allSettled([
      ...(call ? [call.hangup()] : []),
      ...(workspaceId && callRecordId ? [callsApi.hangup(workspaceId, callRecordId)] : []),
    ]);
    releaseCall();
    if (wasInbound) resetState();
    else updateState({ phase: "ended", isMuted: false });
  }, [releaseCall, resetState, updateState]);

  const isSignedIn = Boolean(user);

  /**
   * Registration lifecycle.
   *
   * A signed-in operator with a workspace stays logged in to Telnyx for as long
   * as the dashboard is open — that is the only way an inbound call can ring
   * here — and publishes presence while it holds. Failures back off
   * exponentially so a Telnyx outage or an expired JWT can never turn into a
   * token-minting hot loop against our own API.
   */
  useEffect(() => {
    if (!isSignedIn || !currentWorkspaceId || !canUseSoftphone) {
      // Signed out or between workspaces: tear the headset down on a later
      // tick, so this effect never sets state during the render that ran it.
      const teardown = window.setTimeout(() => void disconnectClient(), 0);
      return () => window.clearTimeout(teardown);
    }

    // Pinned once per effect run: the hoisted helpers below outlive this tick,
    // so they must close over the workspace this registration is actually for.
    const workspaceId = currentWorkspaceId;
    let cancelled = false;
    let attempt = 0;
    let retryTimer: number | null = null;

    async function register() {
      retryTimer = null;
      if (cancelled) return;
      try {
        await ensureConnected(workspaceId);
        if (cancelled) return;
        attempt = 0;
        setIsRegistered(true);
        startPresence(workspaceId);
      } catch {
        if (cancelled) return;
        setIsRegistered(false);
        scheduleRetry();
      }
    }

    function scheduleRetry() {
      if (cancelled || retryTimer !== null) return;
      const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** attempt, RECONNECT_MAX_DELAY_MS);
      attempt += 1;
      retryTimer = window.setTimeout(() => void register(), delay);
    }

    reconnectRef.current = scheduleRetry;
    void register();

    // Closing the tab cancels in-flight XHRs, so the last beat has to be a
    // beacon or the backend keeps ringing a browser that is already gone.
    const clearPresenceOnUnload = () => {
      callsApi.publishPresenceBeacon(workspaceId, false);
    };
    window.addEventListener("pagehide", clearPresenceOnUnload);
    window.addEventListener("beforeunload", clearPresenceOnUnload);

    return () => {
      cancelled = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      reconnectRef.current = null;
      window.removeEventListener("pagehide", clearPresenceOnUnload);
      window.removeEventListener("beforeunload", clearPresenceOnUnload);
      disconnectClient();
    };
  }, [
    canUseSoftphone,
    currentWorkspaceId,
    disconnectClient,
    ensureConnected,
    isSignedIn,
    startPresence,
  ]);

  useEffect(() => {
    if (!user && stateRef.current.phase !== "idle") void hangup();
  }, [hangup, user]);

  useEffect(() => {
    const callWorkspaceId = workspaceIdRef.current;
    if (callWorkspaceId && currentWorkspaceId && callWorkspaceId !== currentWorkspaceId) {
      void hangup();
    }
  }, [currentWorkspaceId, hangup]);

  const value = useMemo<SoftphoneContextValue>(
    () => ({
      ...state,
      isRegistered,
      incoming,
      startCall,
      answer,
      acceptIncoming,
      declineIncoming,
      toggleMute,
      hangup,
      dismiss,
    }),
    [
      acceptIncoming,
      answer,
      declineIncoming,
      dismiss,
      hangup,
      incoming,
      isRegistered,
      startCall,
      state,
      toggleMute,
    ],
  );

  return (
    <SoftphoneContext.Provider value={value}>
      {children}
      {/* Live two-way audio has no prerecorded caption track. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={remoteAudioRef} autoPlay className="sr-only" />
      {incoming ? (
        <IncomingCallBanner
          callerNumber={incoming.callerNumber}
          isConnecting={incoming.isConnecting}
          onAccept={() => void acceptIncoming()}
          onDecline={() => void declineIncoming()}
        />
      ) : null}
      <SoftphoneBar
        {...state}
        onAnswer={answer}
        onToggleMute={toggleMute}
        onHangup={hangup}
        onDismiss={dismiss}
      />
    </SoftphoneContext.Provider>
  );
}

export function useSoftphone(): SoftphoneContextValue {
  const value = useContext(SoftphoneContext);
  if (!value) throw new Error("useSoftphone must be used inside SoftphoneProvider");
  return value;
}
