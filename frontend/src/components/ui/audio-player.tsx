"use client";

import { Play, Pause, Loader2, AlertCircle, RotateCcw } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

interface AudioPlayerProps {
  url: string;
  duration?: number; // Pre-known duration from DB (in seconds)
  className?: string;
}

type PlayerState = "idle" | "loading" | "ready" | "playing" | "paused" | "ended" | "error";

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function AudioPlayer({ url, duration: preloadedDuration, className }: AudioPlayerProps) {
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const [playerState, setPlayerState] = React.useState<PlayerState>(() =>
    preloadedDuration ? "ready" : "idle"
  );
  const [currentTime, setCurrentTime] = React.useState(0);
  const [duration, setDuration] = React.useState(preloadedDuration ?? 0);

  // Load audio metadata when component mounts
  React.useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleLoadStart = () => setPlayerState("loading");
    const handleLoadedMetadata = () => {
      setDuration(audio.duration);
      setPlayerState("ready");
    };
    const handleCanPlay = () => {
      if (playerState === "loading") {
        setPlayerState("ready");
      }
    };
    const handleTimeUpdate = () => setCurrentTime(audio.currentTime);
    const handleEnded = () => setPlayerState("ended");
    const handleError = () => setPlayerState("error");
    const handlePlaying = () => setPlayerState("playing");
    const handlePause = () => {
      if (audio.currentTime < audio.duration) {
        setPlayerState("paused");
      }
    };

    audio.addEventListener("loadstart", handleLoadStart);
    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("canplay", handleCanPlay);
    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("error", handleError);
    audio.addEventListener("playing", handlePlaying);
    audio.addEventListener("pause", handlePause);

    return () => {
      audio.removeEventListener("loadstart", handleLoadStart);
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("canplay", handleCanPlay);
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("error", handleError);
      audio.removeEventListener("playing", handlePlaying);
      audio.removeEventListener("pause", handlePause);
    };
  }, [playerState]);

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (playerState === "playing") {
      audio.pause();
    } else if (playerState === "ended") {
      audio.currentTime = 0;
      await audio.play();
    } else {
      await audio.play();
    }
  };

  const handleSeek = (value: number[]) => {
    const audio = audioRef.current;
    if (!audio || !isFinite(duration) || duration === 0) return;

    const seekTime = (value[0] / 100) * duration;
    audio.currentTime = seekTime;
    setCurrentTime(seekTime);
  };

  const handleRetry = () => {
    const audio = audioRef.current;
    if (!audio) return;

    setPlayerState("idle");
    audio.load();
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
  const isLoading = playerState === "loading";
  const hasError = playerState === "error";
  const canPlay = ["ready", "playing", "paused", "ended"].includes(playerState);

  return (
    <div className={cn("flex items-center gap-3", className)}>
      {/* Recorded calls/voicemails: no caption track is available from the */}
      {/* provider. The audio element is hidden and controlled via the UI below. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} src={url} preload="metadata" className="hidden" />

      {/* Play/Pause Button */}
      <Button
        size="icon"
        variant="secondary"
        className="h-8 w-8 rounded-full shrink-0"
        onClick={hasError ? handleRetry : togglePlayback}
        disabled={isLoading}
        aria-label={
          hasError
            ? "Retry loading audio"
            : playerState === "playing"
              ? "Pause"
              : "Play"
        }
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : hasError ? (
          <RotateCcw className="h-3.5 w-3.5" />
        ) : playerState === "playing" ? (
          <Pause className="h-3.5 w-3.5" />
        ) : (
          <Play className="h-3.5 w-3.5 ml-0.5" />
        )}
      </Button>

      {/* Progress Bar / Error State */}
      {hasError ? (
        <div className="flex-1 flex items-center gap-2 text-destructive">
          <AlertCircle className="h-3.5 w-3.5" />
          <span className="text-xs">Failed to load audio</span>
        </div>
      ) : (
        <>
          {/* Seekable Progress Bar */}
          <div className="flex-1">
            <Slider
              value={[progress]}
              max={100}
              step={0.1}
              onValueChange={handleSeek}
              disabled={!canPlay}
              className="cursor-pointer"
              aria-label="Seek audio"
            />
          </div>

          {/* Time Display */}
          <div className="text-xs text-muted-foreground tabular-nums shrink-0 min-w-[70px] text-right">
            {formatTime(currentTime)} / {formatTime(duration)}
          </div>
        </>
      )}
    </div>
  );
}
