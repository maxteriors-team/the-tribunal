/**
 * Browser session/audio cleanup helpers for the embed voice flow.
 *
 * The OpenAI Realtime voice session owns a small bag of disposable browser
 * resources: an `RTCPeerConnection`, its data channel, the captured microphone
 * `MediaStream`, the playback `<audio>` element, plus a `Web Audio` analyser
 * graph and its `requestAnimationFrame` loop. Tearing these down correctly (and
 * defensively — each close can throw if the object is already in a bad state)
 * is fiddly and easy to get subtly wrong, so it lives here as pure, unit-
 * testable functions instead of being inlined in the React hook.
 */

export interface WebRTCResources {
  peerConnection: RTCPeerConnection | null;
  dataChannel: RTCDataChannel | null;
  audioStream: MediaStream | null;
  audioElement: HTMLAudioElement | null;
}

export interface AudioAnalysisResources {
  audioContext: AudioContext | null;
  analyser: AnalyserNode | null;
  dataArray: Uint8Array<ArrayBuffer> | null;
  animationFrame: number | null;
}

/** A fresh, fully-null set of WebRTC resources. */
export function emptyWebRTCResources(): WebRTCResources {
  return {
    peerConnection: null,
    dataChannel: null,
    audioStream: null,
    audioElement: null,
  };
}

/** A fresh, fully-null set of audio-analysis resources. */
export function emptyAudioAnalysisResources(): AudioAnalysisResources {
  return {
    audioContext: null,
    analyser: null,
    dataArray: null,
    animationFrame: null,
  };
}

/** Run a teardown step, swallowing any error so one failure can't abort the rest. */
function runSafely(step: () => void): void {
  try {
    step();
  } catch {
    // Cleanup is best-effort; a resource may already be closed or detached.
  }
}

/** Stop every track on a media stream (releases the mic indicator). */
export function stopMediaStream(stream: MediaStream | null): void {
  if (!stream) return;
  runSafely(() => {
    for (const track of stream.getTracks()) track.stop();
  });
}

/**
 * Toggle the enabled flag on every audio track of a stream. Returns `true` when
 * a stream was present (so callers can sync mute UI), `false` otherwise.
 */
export function setAudioTracksEnabled(stream: MediaStream | null, enabled: boolean): boolean {
  if (!stream) return false;
  for (const track of stream.getAudioTracks()) track.enabled = enabled;
  return true;
}

/**
 * Cancel the analysis RAF loop and close the `AudioContext`. Safe to call with
 * partially-initialized resources. Does not mutate the passed object — callers
 * reset their own ref afterwards (typically via {@link emptyAudioAnalysisResources}).
 */
export function closeAudioAnalysis(resources: AudioAnalysisResources): void {
  if (resources.animationFrame !== null) {
    runSafely(() => cancelAnimationFrame(resources.animationFrame as number));
  }
  if (resources.audioContext) {
    runSafely(() => void resources.audioContext?.close());
  }
}

/**
 * Tear down all WebRTC resources for a voice session: close the data channel
 * and peer connection, stop the mic tracks, and detach/remove the playback
 * audio element. Each step is isolated so a throw in one does not skip the rest.
 */
export function closeWebRTCResources(resources: WebRTCResources): void {
  const { peerConnection, dataChannel, audioStream, audioElement } = resources;

  if (dataChannel) runSafely(() => dataChannel.close());
  if (peerConnection) runSafely(() => peerConnection.close());
  stopMediaStream(audioStream);
  if (audioElement) {
    runSafely(() => {
      audioElement.srcObject = null;
      audioElement.remove();
    });
  }
}
