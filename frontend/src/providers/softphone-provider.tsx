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

import { SoftphoneBar } from "@/components/calls/softphone-bar";
import { callsApi } from "@/lib/api/calls";
import { queryKeys } from "@/lib/query-keys";
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

interface SoftphoneState {
  phase: SoftphonePhase;
  contactName: string;
  isMuted: boolean;
  startedAt: number | null;
  error: string | null;
}

interface SoftphoneContextValue extends SoftphoneState {
  startCall: (request: BrowserCallRequest) => Promise<void>;
  answer: () => Promise<void>;
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

const SoftphoneContext = createContext<SoftphoneContextValue | null>(null);

function isTerminalCallState(state: string): boolean {
  return state === "hangup" || state === "destroy" || state === "purge";
}

export function SoftphoneProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { currentWorkspaceId } = useWorkspace();
  const [state, setState] = useState<SoftphoneState>(INITIAL_STATE);
  const stateRef = useRef(state);
  const clientRef = useRef<TelnyxRTC | null>(null);
  const callRef = useRef<TelnyxCall | null>(null);
  const callRecordIdRef = useRef<string | null>(null);
  const workspaceIdRef = useRef<string | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);

  const updateState = useCallback((patch: Partial<SoftphoneState>) => {
    setState((current) => {
      const next = { ...current, ...patch };
      stateRef.current = next;
      return next;
    });
  }, []);

  const disconnectClient = useCallback(() => {
    const client = clientRef.current;
    clientRef.current = null;
    callRef.current = null;
    callRecordIdRef.current = null;
    workspaceIdRef.current = null;
    localStreamRef.current?.getTracks().forEach((track) => track.stop());
    localStreamRef.current = null;
    if (client) void client.disconnect().catch(() => undefined);
  }, []);

  const dismiss = useCallback(() => {
    disconnectClient();
    stateRef.current = INITIAL_STATE;
    setState(INITIAL_STATE);
  }, [disconnectClient]);

  useEffect(() => disconnectClient, [disconnectClient]);

  const handleNotification = useCallback(
    (notification: INotification) => {
      if (notification.type !== "callUpdate" || !notification.call) return;

      const call = notification.call;
      const callState = String(call.state).toLowerCase();
      if (!callRef.current) callRef.current = call;
      if (callRef.current.id !== call.id) return;

      if (callState === "active") {
        updateState({
          phase: "active",
          startedAt: stateRef.current.startedAt ?? Date.now(),
          error: null,
        });
      } else if (isTerminalCallState(callState)) {
        callRef.current = null;
        callRecordIdRef.current = null;
        updateState({ phase: "ended", isMuted: false });
        disconnectClient();
      } else if (stateRef.current.phase === "waiting") {
        updateState({ phase: "ringing" });
      }
    },
    [disconnectClient, updateState],
  );

  const connect = useCallback(
    async (workspaceId: string): Promise<void> => {
      const { token } = await callsApi.getWebRTCToken(workspaceId);
      const { TelnyxRTC: TelnyxRTCClient } = await import("@telnyx/webrtc");
      const client = new TelnyxRTCClient({ login_token: token });
      if (remoteAudioRef.current) client.remoteElement = remoteAudioRef.current;
      clientRef.current = client;
      client.on("telnyx.notification", handleNotification);

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
    },
    [handleNotification],
  );

  const startCall = useCallback(
    async (request: BrowserCallRequest) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Browser calling needs desktop Chrome and microphone access.");
      }
      if (!["idle", "ended", "error"].includes(stateRef.current.phase)) {
        throw new Error("Finish the current browser call before starting another.");
      }

      disconnectClient();
      updateState({
        phase: "preparing",
        contactName: request.contactName,
        isMuted: false,
        startedAt: null,
        error: null,
      });

      try {
        workspaceIdRef.current = request.workspaceId;
        await connect(request.workspaceId);
        updateState({ phase: "waiting" });
        const callRecord = await callsApi.initiate(request.workspaceId, {
          to_number: request.toNumber,
          from_phone_number: request.fromPhoneNumber,
          contact_phone: request.toNumber,
          mode: "browser",
        });
        callRecordIdRef.current = callRecord.id;
        void queryClient.invalidateQueries({
          queryKey: queryKeys.calls.all(request.workspaceId),
        });
      } catch (error) {
        disconnectClient();
        const message = error instanceof Error ? error.message : "Browser calling failed.";
        updateState({ phase: "error", error: message });
        throw error;
      }
    },
    [connect, disconnectClient, queryClient, updateState],
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
      disconnectClient();
      updateState({ phase: "error", error: "Microphone access failed. Check Chrome permissions." });
    }
  }, [disconnectClient, updateState]);

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
    const workspaceId = workspaceIdRef.current;
    const callRecordId = callRecordIdRef.current;
    const call = callRef.current;
    await Promise.allSettled([
      ...(call ? [call.hangup()] : []),
      ...(workspaceId && callRecordId ? [callsApi.hangup(workspaceId, callRecordId)] : []),
    ]);
    updateState({ phase: "ended", isMuted: false });
    disconnectClient();
  }, [disconnectClient, updateState]);

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
    () => ({ ...state, startCall, answer, toggleMute, hangup, dismiss }),
    [answer, dismiss, hangup, startCall, state, toggleMute],
  );

  return (
    <SoftphoneContext.Provider value={value}>
      {children}
      {/* Live two-way audio has no prerecorded caption track. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={remoteAudioRef} autoPlay className="sr-only" />
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
