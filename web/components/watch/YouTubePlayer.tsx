"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

// Minimal typing for the YouTube IFrame Player API.
type YTPlayer = {
  seekTo(s: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  pauseVideo(): void;
  getCurrentTime(): number;
  getPlayerState(): number;
  destroy(): void;
};
declare global {
  interface Window {
    YT?: { Player: new (el: HTMLElement, opts: unknown) => YTPlayer; PlayerState: Record<string, number> };
    onYouTubeIframeAPIReady?: () => void;
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
 * The official YouTube embedded player (privacy-enhanced host), with YouTube's own defaults (speed, captions).
 * Nothing is drawn over it and its controls aren't changed: our statement track sits underneath, as YouTube's API
 * policies require (III.I.6).
 */
export const YouTubePlayer = forwardRef<PlayerHandle, Props>(function YouTubePlayer(
  { videoId, start, autoplay = false, onPlayingChange, onError, onReady }, ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);
  const isReady = useRef(false);
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
            cbs.current.onReady?.();
            if (autoplay) player.current?.playVideo();
          },
          onStateChange: (e: { data: number }) => cbs.current.onPlayingChange?.(e.data === 1),
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
