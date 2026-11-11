import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C, Caption, FONT, Scene, Svg, hexPoints, ramp} from '../lib';

const Plane: React.FC<{x: number; y: number}> = ({x, y}) => (
  <g transform={`translate(${x} ${y})`}>
    <path d="M-34 0 L18 -5 L34 0 L18 5 Z" fill={C.text} />
    <path d="M-6 -3 L-18 -24 L-8 -24 L8 -3 Z" fill={C.text} />
    <path d="M-6 3 L-18 24 L-8 24 L8 3 Z" fill={C.text} />
    <path d="M-30 -1 L-38 -12 L-32 -12 L-24 -1 Z" fill={C.text} />
  </g>
);

const Ship: React.FC<{x: number; y: number}> = ({x, y}) => (
  <g transform={`translate(${x} ${y})`} fill={C.dim}>
    <path d="M-70 -18 L70 -18 L52 6 L-56 6 Z" />
    <rect x={-30} y={-44} width={44} height={26} rx={3} />
    <rect x={-8} y={-64} width={10} height={20} />
  </g>
);

const Truck: React.FC<{x: number; y: number}> = ({x, y}) => (
  <g transform={`translate(${x} ${y})`} fill={C.dim}>
    <rect x={-58} y={-46} width={78} height={38} rx={4} />
    <path d="M24 -34 L46 -34 L58 -18 L58 -8 L24 -8 Z" />
    <circle cx={-34} cy={-4} r={11} />
    <circle cx={36} cy={-4} r={11} />
  </g>
);

const Tractor: React.FC<{x: number; y: number}> = ({x, y}) => (
  <g transform={`translate(${x} ${y})`} fill={C.dim}>
    <rect x={-22} y={-58} width={34} height={30} rx={4} />
    <rect x={-22} y={-32} width={66} height={20} rx={4} />
    <circle cx={-16} cy={-10} r={20} />
    <circle cx={38} cy={-4} r={12} />
  </g>
);

const Crane: React.FC<{x: number; y: number}> = ({x, y}) => (
  <g transform={`translate(${x} ${y})`} stroke={C.dim} strokeWidth={8} fill="none" strokeLinecap="round">
    <path d="M-20 0 L-20 -92 L50 -92" />
    <path d="M20 0 L20 -92" />
    <path d="M36 -92 L36 -52" strokeWidth={4} />
    <rect x={24} y={-52} width={24} height={16} fill={C.dim} stroke="none" />
  </g>
);

// Which hexes in the sky row the aircraft reports turn "affected".
const AFFECTED = new Set([5, 6, 7, 8]);

export const Gap: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const n = 13;
  const r = 52;
  const x0 = 330;
  const step = 105;
  const planes = [
    {y: 300, speed: 9.5, start: -160},
    {y: 372, speed: 7.2, start: -520},
    {y: 250, speed: 11.0, start: -900},
  ];
  const lead = Math.max(...planes.map((p) => p.start + p.speed * f));
  const hatch = ramp(f, 80, 110);
  return (
    <Scene f={f} dur={dur}>
      <Svg>
        <text x={120} y={128} fill={C.dim} fontSize={28} fontFamily={FONT}>Sky: mapped from aircraft reports</text>
        {Array.from({length: n}, (_, i) => {
          const cx = x0 + i * step;
          const lit = ramp(lead, cx - 40, cx + 60);
          const color = AFFECTED.has(i) ? C.jam : C.ok;
          return (
            <g key={i}>
              <polygon points={hexPoints(cx, 190, r)} fill={color} opacity={0.12 + 0.6 * lit * (AFFECTED.has(i) ? 1 : 0.35)} />
              <polygon points={hexPoints(cx, 190, r)} fill="none" stroke={lit > 0.1 ? color : C.line} strokeWidth={2.5} opacity={0.9} />
            </g>
          );
        })}
        {planes.map((p, i) => {
          const x = p.start + p.speed * f;
          return (
            <g key={i} opacity={x > -80 && x < 2000 ? 1 : 0}>
              <line x1={x - 220} y1={p.y} x2={x - 44} y2={p.y} stroke={C.dim} strokeWidth={2} strokeDasharray="4 10" opacity={0.6} />
              <line x1={x} y1={p.y - 30} x2={x} y2={245} stroke={C.accent} strokeWidth={2} strokeDasharray="3 9" opacity={0.55} />
              <Plane x={x} y={p.y} />
            </g>
          );
        })}

        <rect x={120} y={470} width={1680} height={230} rx={18} fill="url(#hatch)" opacity={hatch} />
        <rect x={120} y={470} width={1680} height={230} rx={18} fill="none" stroke={C.line} strokeWidth={2} />
        <line x1={120} y1={700} x2={1800} y2={700} stroke={C.dim} strokeWidth={3} />
        <Crane x={300} y={700} />
        <Ship x={600} y={694} />
        <Truck x={1260} y={700} />
        <Tractor x={1580} y={700} />
        <g opacity={hatch}>
          <rect x={720} y={520} width={480} height={64} rx={32} fill={C.bg} stroke="#5b6f88" strokeWidth={2} />
          <text x={960} y={563} fill={C.text} fontSize={30} fontWeight={600} textAnchor="middle" fontFamily={FONT}>
            Ground and sea level: no data
          </text>
        </g>
      </Svg>
      <Caption
        f={f}
        kicker="The gap"
        title="Interference maps today are built from aircraft reports."
        sub="They show the sky. Ports, shipping lanes, roads and fields stay blank."
      />
    </Scene>
  );
};
