// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import type { ReactNode } from "react";

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-[640px] border border-hev-cyan/70 bg-hev-panel">
        <header className="flex h-9 items-center justify-between border-b border-hev-line px-3">
          <h2 className="hev-label m-0 font-normal text-hev-cyan">{title}</h2>
          <button type="button" onClick={onClose} className="h-6 border border-hev-line px-2 text-[11px] tracking-[0.14em] text-hev-dim hover:text-hev-white">CLOSE</button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
