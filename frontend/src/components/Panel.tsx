// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import type { ReactNode } from "react";

interface Props {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  testId?: string;
}

export function Panel({ title, right, children, className = "", bodyClassName = "", testId }: Props) {
  return (
    <section data-testid={testId} className={`relative flex min-h-0 min-w-0 flex-col border border-[#333333] bg-[#050505] ${className}`}>
      <span className="pointer-events-none absolute -left-px -top-px h-2 w-2 border-l-2 border-t-2 border-[#00ff00]" />
      <span className="pointer-events-none absolute -right-px -top-px h-2 w-2 border-r-2 border-t-2 border-[#00ff00]" />
      <header className="flex h-7 shrink-0 items-center justify-between border-b border-[#333333] bg-[#0d0d0d] px-2.5">
        <h2 className="hmi-sans m-0 text-[11px] font-bold uppercase tracking-[0.12em] text-white">{title}</h2>
        {right}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex h-[18px] shrink-0 items-center whitespace-nowrap border px-1.5 text-[10px] font-bold uppercase leading-none tracking-[0.12em] ${className}`}>
      {children}
    </span>
  );
}

export function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;
  if (source === "SIMULATED") return <Chip className="border-hev-amber/70 bg-[#1a1100] text-hev-amber">SIM</Chip>;
  if (source === "CREW_INPUT") return <Chip className="border-hev-white/50 text-hev-white">CREW</Chip>;
  if (source === "SENSOR") return <Chip className="border-hev-green/70 bg-[#001a00] text-hev-green">SENSOR</Chip>;
  return <Chip className="border-hev-dim text-hev-dim">{source}</Chip>;
}

export function Sparkline({ points, color = "#00ff00", width = 120, height = 28, min, max }: {
  points: number[]; color?: string; width?: number; height?: number; min?: number; max?: number;
}) {
  if (points.length < 2) return <svg width={width} height={height} aria-hidden />;
  const lo = min ?? Math.min(...points);
  const hi = max ?? Math.max(...points);
  const span = hi - lo || 1;
  const d = points
    .map((v, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - lo) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.3} />
    </svg>
  );
}
