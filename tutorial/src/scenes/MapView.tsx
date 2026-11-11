import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C, Caption, FONT, Scene, Svg, hexGrid, hexPoints, ramp} from '../lib';

const GRID = hexGrid(150, 150, 1770, 700, 50);
const TOWNS = [[520, 420, 210], [1180, 330, 250], [1500, 600, 150]];
const INCIDENT = [[1150, 360, 95]];

const kind = (x: number, y: number) => {
  if (INCIDENT.some(([cx, cy, r]) => Math.hypot(x - cx, y - cy) < r)) return 'incident';
  if (TOWNS.some(([cx, cy, r]) => Math.hypot(x - cx, y - cy) < r)) return 'covered';
  return 'none';
};

export const MapView: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const cov = ramp(f, 20, 50);
  const inc = ramp(f, 56, 80);
  const veil = ramp(f, 92, 124);
  const legend = [
    {c: C.jam, t: 'Incident'},
    {c: C.ok, t: 'Covered, no incident detected'},
    {c: 'hatch', t: 'No data'},
  ];
  return (
    <Scene f={f} dur={dur}>
      <Svg>
        <rect x={120} y={110} width={1680} height={640} rx={28} fill="#0e1620" stroke={C.line} strokeWidth={2} />
        <clipPath id="mapclip"><rect x={120} y={110} width={1680} height={640} rx={28} /></clipPath>
        <g clipPath="url(#mapclip)">
          {GRID.map((h, i) => {
            const k = kind(h.x, h.y);
            const pts = hexPoints(h.x, h.y, 48);
            if (k === 'incident') return <polygon key={i} points={pts} fill={C.jam} opacity={0.15 + 0.6 * inc} stroke={C.jam} strokeWidth={2} />;
            if (k === 'covered') return <polygon key={i} points={pts} fill={C.ok} opacity={0.06 + 0.3 * cov} stroke={C.ok} strokeWidth={1.5} />;
            return (
              <g key={i}>
                <polygon points={pts} fill="url(#hatch)" opacity={veil} />
                <polygon points={pts} fill="none" stroke={C.grid} strokeWidth={1.5} />
              </g>
            );
          })}
        </g>
        <g opacity={ramp(f, 126, 142)}>
          <rect x={206} y={612} width={250} height={64} rx={32} fill={C.bg} stroke="#5b6f88" strokeWidth={2} />
          <text x={331} y={655} fill={C.text} fontSize={30} fontWeight={600} textAnchor="middle" fontFamily={FONT}>No data here</text>
        </g>
        <g opacity={ramp(f, 30, 46)}>
          <rect x={1330} y={136} width={444} height={176} rx={20} fill={C.panel} stroke={C.line} strokeWidth={2} />
          {legend.map((l, i) => (
            <g key={l.t}>
              <rect x={1356} y={160 + i * 48} width={30} height={30} rx={7} fill={l.c === 'hatch' ? 'url(#hatch)' : l.c}
                opacity={l.c === C.ok ? 0.6 : 1} stroke={C.line} strokeWidth={1.5} />
              <text x={1402} y={184 + i * 48} fill={C.text} fontSize={26} fontFamily={FONT}>{l.t}</text>
            </g>
          ))}
        </g>
      </Svg>
      <Caption
        f={f}
        kicker="An honest map"
        title="Where there are no phones, the map says so."
        sub="No data is never drawn as clean. Every incident shows its confidence, device count and coverage."
      />
    </Scene>
  );
};
