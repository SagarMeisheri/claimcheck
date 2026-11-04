"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** Previous / Next buttons for stepping through statements, in a drawer bar or a docked panel. */
export function PaneNav({ hasPrev, hasNext, onPrev, onNext, what = "statement" }: {
  hasPrev: boolean; hasNext: boolean; onPrev(): void; onNext(): void; what?: string;
}) {
  return (
    <div className="sdrawer-nav">
      <button type="button" className="btn secondary small" onClick={onPrev} disabled={!hasPrev} aria-label={`Previous ${what}`}>‹ Previous</button>
      <button type="button" className="btn secondary small" onClick={onNext} disabled={!hasNext} aria-label={`Next ${what}`}>Next ›</button>
    </div>
  );
}

/**
 * A panel over the page: from the right on wide screens, from the bottom on phones. The page underneath never moves.
 * Esc or the backdrop closes it; ← → step with Previous / Next. Focus goes to the close button and comes back after.
 */
export function Drawer({ onClose, labelledBy, accent, nav, onPrev, onNext, children }: {
  onClose(): void; labelledBy: string; accent?: string; nav?: ReactNode; onPrev?(): void; onNext?(): void; children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const lock = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = lock; before?.focus?.(); };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") onNext?.();
      else if (e.key === "ArrowLeft") onPrev?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onNext, onPrev]);

  return (
    <div className="sdrawer-wrap">
      <div className="sdrawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="sdrawer" role="dialog" aria-modal="true" aria-labelledby={labelledBy}
             style={accent ? { ["--stype" as string]: accent } : undefined}>
        <div className="sdrawer-bar">
          <span className="sdrawer-grip" aria-hidden="true" />
          {nav ?? <span className="sdrawer-nav" />}
          <button ref={closeRef} type="button" className="iconbtn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="sdrawer-body">{children}</div>
      </aside>
    </div>
  );
}
