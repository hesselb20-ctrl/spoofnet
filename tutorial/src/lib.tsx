import React from 'react';
import {AbsoluteFill, Easing, interpolate, random} from 'remotion';

export const W = 1920;
export const H = 1080;
export const FPS = 30;

export const C = {
  bg: '#0b1017',
  panel: '#121a25',
  line: '#26364a',
  grid: '#1a2634',
  text: '#eef2f7',
  dim: '#93a4b8',
  accent: '#4c9bff',
  jam: '#f0683c',
  spoof: '#a777f2',
  meacon: '#2fb5c6',
  ok: '#3fbf7f',
  warn: '#f2b84b',
};

export const FONT = '"Segoe UI", Inter, system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';
export const MONO = 'Consolas, "Cascadia Mono", Menlo, monospace';

export const ease = Easing.bezier(0.2, 0.8, 0.2, 1);

/** Eased 0..1 (or from..to) between frames a and b, clamped outside. */
export const ramp = (f: number, a: number, b: number, from = 0, to = 1) =>
  interpolate(f, [a, b], [from, to], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

/** Deterministic pseudo-random number in [0, 1). */
export const rnd = (seed: string | number) => random(`spoofnet-${seed}`);

/** Scene wrapper: fades in and out so scenes cross-dissolve on the shared background. */
export const Scene: React.FC<{f: number; dur: number; children: React.ReactNode}> = ({f, dur, children}) => {
  const opacity = Math.min(ramp(f, 0, 12), ramp(f, dur - 10, dur, 1, 0));
  return <AbsoluteFill style={{opacity, fontFamily: FONT, color: C.text}}>{children}</AbsoluteFill>;
};

/** The text block at the bottom of every scene. */
export const Caption: React.FC<{f: number; kicker: string; title: string; sub?: string}> = ({f, kicker, title, sub}) => {
  const line = (delay: number): React.CSSProperties => ({
    opacity: ramp(f, delay, delay + 14),
    transform: `translateY(${ramp(f, delay, delay + 18, 18, 0)}px)`,
  });
  return (
    <div style={{position: 'absolute', left: 120, right: 120, top: 800}}>
      <div style={{...line(6), fontSize: 26, fontWeight: 600, letterSpacing: 3, textTransform: 'uppercase', color: C.accent}}>
        {kicker}
      </div>
      <div style={{...line(12), fontSize: 58, fontWeight: 650, lineHeight: 1.14, marginTop: 12, letterSpacing: -0.5}}>{title}</div>
      {sub ? <div style={{...line(24), fontSize: 34, color: C.dim, marginTop: 14, lineHeight: 1.3}}>{sub}</div> : null}
    </div>
  );
};

export const Chip: React.FC<{color: string; children: React.ReactNode; style?: React.CSSProperties; solid?: boolean}> = ({
  color, children, style, solid,
}) => (
  <div
    style={{
      display: 'inline-block', padding: '10px 22px', borderRadius: 999, fontSize: 28, fontWeight: 600,
      color: solid ? '#0b1017' : color, background: solid ? color : `${color}22`, border: `2px solid ${color}`,
      whiteSpace: 'nowrap', ...style,
    }}
  >
    {children}
  </div>
);

export const Panel: React.FC<{x: number; y: number; w: number; h: number; children?: React.ReactNode; style?: React.CSSProperties}> = ({
  x, y, w, h, children, style,
}) => (
  <div
    style={{
      position: 'absolute', left: x, top: y, width: w, height: h, background: C.panel, border: `1.5px solid ${C.line}`,
      borderRadius: 28, ...style,
    }}
  >
    {children}
  </div>
);

/** Full-frame SVG layer in video pixels. */
export const Svg: React.FC<{children: React.ReactNode; width?: number; height?: number}> = ({children, width = W, height = H}) => (
  <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{position: 'absolute', left: 0, top: 0}}>
    <defs>
      <pattern id="hatch" width="18" height="18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="18" height="18" fill="#0f1722" />
        <line x1="0" y1="0" x2="0" y2="18" stroke="#46566b" strokeWidth="5" />
      </pattern>
    </defs>
    {children}
  </svg>
);

/** Flat-topped hexagon outline as an SVG points string. */
export const hexPoints = (cx: number, cy: number, r: number) =>
  Array.from({length: 6}, (_, i) => {
    const a = (Math.PI / 3) * i;
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(' ');

export type Hex = {q: number; r: number; x: number; y: number};

/** Flat-topped hex grid covering a rectangle. */
export const hexGrid = (x0: number, y0: number, x1: number, y1: number, r: number): Hex[] => {
  const out: Hex[] = [];
  const dx = 1.5 * r;
  const dy = Math.sqrt(3) * r;
  for (let q = 0; x0 + q * dx <= x1 + r; q++) {
    for (let row = 0; y0 + row * dy <= y1 + r; row++) {
      out.push({q, r: row, x: x0 + q * dx, y: y0 + row * dy + (q % 2 ? dy / 2 : 0)});
    }
  }
  return out;
};

/** Signal-strength bars with a label under each. Values are 0..1. */
export const Bars: React.FC<{
  x: number; y: number; w: number; h: number; values: number[]; labels?: string[]; color?: string; colors?: string[];
}> = ({x, y, w, h, values, labels, color = C.accent, colors}) => {
  const n = values.length;
  const gap = 14;
  const bw = (w - gap * (n - 1)) / n;
  return (
    <g>
      <line x1={x} y1={y + h} x2={x + w} y2={y + h} stroke={C.line} strokeWidth={2} />
      {values.map((v, i) => {
        const bh = Math.max(4, h * Math.min(Math.max(v, 0), 1));
        return (
          <g key={i}>
            <rect x={x + i * (bw + gap)} y={y} width={bw} height={h} rx={8} fill="#182331" />
            <rect x={x + i * (bw + gap)} y={y + h - bh} width={bw} height={bh} rx={8} fill={colors ? colors[i] : color} />
            {labels ? (
              <text x={x + i * (bw + gap) + bw / 2} y={y + h + 34} fill={C.dim} fontSize={22} textAnchor="middle" fontFamily={MONO}>
                {labels[i]}
              </text>
            ) : null}
          </g>
        );
      })}
    </g>
  );
};

/** Horizontal meter, used for receiver gain. Value is 0..1. */
export const Meter: React.FC<{x: number; y: number; w: number; value: number; label: string; color?: string}> = ({
  x, y, w, value, label, color = C.ok,
}) => (
  <g>
    <text x={x} y={y - 14} fill={C.dim} fontSize={26} fontFamily={FONT}>{label}</text>
    <rect x={x} y={y} width={w} height={22} rx={11} fill="#182331" />
    <rect x={x} y={y} width={Math.max(22, w * value)} height={22} rx={11} fill={color} />
  </g>
);

export const Phone: React.FC<{x: number; y: number; w: number; h: number; children?: React.ReactNode}> = ({x, y, w, h, children}) => (
  <g>
    <rect x={x} y={y} width={w} height={h} rx={w * 0.16} fill="#0f1620" stroke="#5b6f88" strokeWidth={4} />
    <rect x={x + w * 0.36} y={y + 14} width={w * 0.28} height={10} rx={5} fill="#5b6f88" />
    {children}
  </g>
);

export const Satellite: React.FC<{x: number; y: number; s?: number; color?: string}> = ({x, y, s = 1, color = C.dim}) => (
  <g transform={`translate(${x} ${y}) scale(${s}) rotate(-25)`}>
    <rect x={-9} y={-9} width={18} height={18} rx={4} fill={color} />
    <rect x={-40} y={-6} width={26} height={12} rx={2} fill={color} opacity={0.75} />
    <rect x={14} y={-6} width={26} height={12} rx={2} fill={color} opacity={0.75} />
  </g>
);

/** Small tick or open ring, for status lists. */
export const Mark: React.FC<{done: boolean; size?: number}> = ({done, size = 44}) => (
  <svg width={size} height={size} viewBox="0 0 44 44" style={{flex: 'none'}}>
    <circle cx={22} cy={22} r={19} fill={done ? `${C.ok}26` : 'none'} stroke={done ? C.ok : C.warn} strokeWidth={3}
      strokeDasharray={done ? undefined : '6 6'} />
    {done ? <path d="M12 23 L19 30 L32 15" fill="none" stroke={C.ok} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" /> : null}
  </svg>
);
