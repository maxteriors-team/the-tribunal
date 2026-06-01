import { afterEach, describe, expect, it, vi } from "vitest";

import {
  closeAudioAnalysis,
  closeWebRTCResources,
  emptyAudioAnalysisResources,
  emptyWebRTCResources,
  setAudioTracksEnabled,
  stopMediaStream,
  type AudioAnalysisResources,
  type WebRTCResources,
} from "@/lib/embed/session";

afterEach(() => {
  vi.restoreAllMocks();
});

// --- Fakes ----------------------------------------------------------------

function makeTrack(kind: "audio" | "video" = "audio") {
  return {
    kind,
    enabled: true,
    stop: vi.fn(),
  };
}

function makeStream(tracks: ReturnType<typeof makeTrack>[]): MediaStream {
  return {
    getTracks: () => tracks,
    getAudioTracks: () => tracks.filter((t) => t.kind === "audio"),
  } as unknown as MediaStream;
}

// --- Tests ----------------------------------------------------------------

describe("empty resource factories", () => {
  it("emptyWebRTCResources is all null", () => {
    expect(emptyWebRTCResources()).toEqual({
      peerConnection: null,
      dataChannel: null,
      audioStream: null,
      audioElement: null,
    });
  });

  it("emptyAudioAnalysisResources is all null", () => {
    expect(emptyAudioAnalysisResources()).toEqual({
      audioContext: null,
      analyser: null,
      dataArray: null,
      animationFrame: null,
    });
  });

  it("returns a fresh object each call (no shared mutable state)", () => {
    expect(emptyWebRTCResources()).not.toBe(emptyWebRTCResources());
  });
});

describe("stopMediaStream", () => {
  it("stops every track on the stream", () => {
    const tracks = [makeTrack(), makeTrack("video")];
    stopMediaStream(makeStream(tracks));
    for (const track of tracks) expect(track.stop).toHaveBeenCalledTimes(1);
  });

  it("is a no-op for null", () => {
    expect(() => stopMediaStream(null)).not.toThrow();
  });

  it("swallows errors thrown while stopping tracks", () => {
    const track = makeTrack();
    track.stop.mockImplementation(() => {
      throw new Error("already stopped");
    });
    expect(() => stopMediaStream(makeStream([track]))).not.toThrow();
  });
});

describe("setAudioTracksEnabled", () => {
  it("toggles only audio tracks and returns true when a stream is present", () => {
    const audio = makeTrack("audio");
    const video = makeTrack("video");
    const result = setAudioTracksEnabled(makeStream([audio, video]), false);

    expect(result).toBe(true);
    expect(audio.enabled).toBe(false);
    // Video track left untouched.
    expect(video.enabled).toBe(true);
  });

  it("returns false for a null stream", () => {
    expect(setAudioTracksEnabled(null, true)).toBe(false);
  });
});

describe("closeAudioAnalysis", () => {
  it("cancels the animation frame and closes the audio context", () => {
    const cancelSpy = vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
    const close = vi.fn();
    const resources: AudioAnalysisResources = {
      audioContext: { close } as unknown as AudioContext,
      analyser: null,
      dataArray: null,
      animationFrame: 7,
    };

    closeAudioAnalysis(resources);

    expect(cancelSpy).toHaveBeenCalledWith(7);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("does nothing harmful with empty resources", () => {
    expect(() => closeAudioAnalysis(emptyAudioAnalysisResources())).not.toThrow();
  });

  it("swallows a throwing context close", () => {
    const resources: AudioAnalysisResources = {
      audioContext: {
        close: () => {
          throw new Error("bad state");
        },
      } as unknown as AudioContext,
      analyser: null,
      dataArray: null,
      animationFrame: null,
    };
    expect(() => closeAudioAnalysis(resources)).not.toThrow();
  });
});

describe("closeWebRTCResources", () => {
  it("closes the channel, peer connection, stops tracks, and detaches audio", () => {
    const dataChannel = { close: vi.fn() };
    const peerConnection = { close: vi.fn() };
    const track = makeTrack();
    const audioElement = {
      srcObject: {} as MediaStream | null,
      remove: vi.fn(),
    };

    const resources: WebRTCResources = {
      dataChannel: dataChannel as unknown as RTCDataChannel,
      peerConnection: peerConnection as unknown as RTCPeerConnection,
      audioStream: makeStream([track]),
      audioElement: audioElement as unknown as HTMLAudioElement,
    };

    closeWebRTCResources(resources);

    expect(dataChannel.close).toHaveBeenCalledTimes(1);
    expect(peerConnection.close).toHaveBeenCalledTimes(1);
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(audioElement.srcObject).toBeNull();
    expect(audioElement.remove).toHaveBeenCalledTimes(1);
  });

  it("is a no-op with all-null resources", () => {
    expect(() => closeWebRTCResources(emptyWebRTCResources())).not.toThrow();
  });

  it("continues cleanup even when the peer connection throws on close", () => {
    const track = makeTrack();
    const resources: WebRTCResources = {
      dataChannel: null,
      peerConnection: {
        close: () => {
          throw new Error("ICE failed");
        },
      } as unknown as RTCPeerConnection,
      audioStream: makeStream([track]),
      audioElement: null,
    };

    closeWebRTCResources(resources);

    // Track stop still ran despite the peer connection throwing.
    expect(track.stop).toHaveBeenCalledTimes(1);
  });
});
