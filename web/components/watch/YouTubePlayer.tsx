"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

// Minimal typing for the YouTube IFrame Player API.
type YTPlayer = {
  seekTo(s: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  pauseVideo(): void;
  getCurrentTime(): number;
  getPlayerState(): number;
  setPlaybackRate(rate: number): void;
  loadModule?(name: string): void;
  setOption?(module: string, option: string, value: unknown): void;
  destroy(): void;
};
declare global {
  interface Window {
    YT?: { Player: new (el: HTMLElement, opts: unknown) => YTPlayer; PlayerState: Record<string, number> };
    onYouTubeIframeAPIReady?: () => void;
  }
}

/** Every video starts at this speed so viewers don't have to change it. They can still pick another speed in the player. */
const DEFAULT_RATE = 1.5;
/** Caption size: -1 is 75% (0 = 100%, 1 = 150%). Undocumented YouTube option, so it is best effort and never throws. */
const CAPTION_SIZE = -1;

function applyDefaults(p: YTPlayer | null) {
  if (!p) return;
  p.setPlaybackRate(DEFAULT_RATE);
  try {
    p.loadModule?.("captions");
    p.setOption?.("captions", "fontSize", CAPTION_SIZE);
  } catch {
    /* YouTube changed or removed the option: captions just keep their normal size */
  }
}

let apiPromise: Promise<NonNullable<Window["YT"]>> | null = null;

function loadApi(): Promise<NonNullable<Window["YT"]>> {
  if (typeof window !== "undefined" && window.YT?.Player) return Promise.resolve(window.YT);
  if (!apiPromise) {
    apiPromise = new Promise((resolve) => {
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        prev?.();
        resolve(window.YT!);
      };
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      s.async = true;
      document.head.appendChild(s);
    });
  }
  return apiPromise;
}

export type PlayerHandle = {
  seekTo(seconds: number, play?: boolean): void;
  play(): void;
  pause(): void;
  time(): number;
  isPlaying(): boolean;
  ready(): boolean;
};

type Props = {
  videoId: string;
  start: number;
  autoplay?: boolean;
  onPlayingChange?(playing: boolean): void;
  onError?(code: number): void;
  onReady?(): void;
};

/**
 * The official YouTube embedded player (privacy-enhanced host). Nothing is drawn over it:
 * our claim track sits underneath, as YouTube's API policies require.
 */
export const YouTubePlayer = forwardRef<PlayerHandle, Props>(function YouTubePlayer(
  { videoId, start, autoplay = false, onPlayingChange, onError, onReady }, ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);
  const isReady = useRef(false);
  const rateApplied = useRef(false);
  const cbs = useRef({ onPlayingChange, onError, onReady });
  cbs.current = { onPlayingChange, onError, onReady };

  useEffect(() => {
    let cancelled = false;
    loadApi().then((YT) => {
      if (cancelled || !host.current) return;
      const mount = document.createElement("div");
      host.current.appendChild(mount);
      player.current = new YT.Player(mount, {
        host: "https://www.youtube-nocookie.com",
        videoId,
        width: "100%",
        height: "100%",
        playerVars: { playsinline: 1, rel: 0, controls: 1, fs: 1, iv_load_policy: 3, cc_load_policy: 0, start: Math.max(0, Math.floor(start)), origin: window.location.origin },
        events: {
          onReady: () => {
            isReady.current = true;
            applyDefaults(player.current);
            cbs.current.onReady?.();
            if (autoplay) player.current?.playVideo();
          },
          onStateChange: (e: { data: number }) => {
            // YouTube can reset the rate when playback first starts, so set it once more then. After that the viewer's choice stands.
            if (e.data === 1 && !rateApplied.current) {
              rateApplied.current = true;
              applyDefaults(player.current);
            }
            cbs.current.onPlayingChange?.(e.data === 1);
          },
          onError: (e: { data: number }) => cbs.current.onError?.(e.data),
        },
      });
    });
    return () => {
      cancelled = true;
      try {
        player.current?.destroy();
      } catch {
        /* already gone */
      }
      player.current = null;
      isReady.current = false;
      rateApplied.current = false;
    };
    // The player is created once per video; start/autoplay only apply to the first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  useImperativeHandle(ref, () => ({
    seekTo(seconds, play = false) {
      const p = player.current;
      if (!p || !isReady.current) return;
      p.seekTo(Math.max(0, seconds), true);
      if (play) p.playVideo();
    },
    play: () => player.current?.playVideo(),
    pause: () => player.current?.pauseVideo(),
    time: () => (isReady.current && player.current ? player.current.getCurrentTime() || 0 : 0),
    isPlaying: () => (isReady.current && player.current ? player.current.getPlayerState() === 1 : false),
    ready: () => isReady.current,
  }), []);

  return <div ref={host} className="yt-host" />;
});
