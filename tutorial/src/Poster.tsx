import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C, FONT, Phone, Satellite, Svg, hexGrid, hexPoints} from './lib';

const GRID = hexGrid(930, 60, 1560, 760, 58);
const HOT = [[1090, 540, 100]];
const COVERED = [[1250, 440, 250]];

/** The banner at the top of the README. */
export const Poster: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: C.bg, fontFamily: FONT, color: C.text}}>
    <Svg width={1600} height={800}>
      {GRID.map((h, i) => {
        const pts = hexPoints(h.x, h.y, 56);
        const hot = HOT.some(([x, y, r]) => Math.hypot(h.x - x, h.y - y) < r);
        const cov = COVERED.some(([x, y, r]) => Math.hypot(h.x - x, h.y - y) < r);
        if (hot) return <polygon key={i} points={pts} fill={C.jam} opacity={0.75} stroke={C.jam} strokeWidth={2} />;
        if (cov) return <polygon key={i} points={pts} fill={C.ok} opacity={0.28} stroke={C.ok} strokeWidth={1.5} />;
        return (
          <g key={i}>
            <polygon points={pts} fill="url(#hatch)" opacity={0.9} />
            <polygon points={pts} fill="none" stroke={C.grid} strokeWidth={1.5} />
          </g>
        );
      })}
      <rect x={840} y={0} width={240} height={800} fill="url(#fade)" />
      <defs>
        <linearGradient id="fade" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor={C.bg} stopOpacity={1} />
          <stop offset="1" stopColor={C.bg} stopOpacity={0} />
        </linearGradient>
      </defs>
      {[[1130, 150], [1320, 96], [1510, 150]].map(([x, y], i) => (
        <g key={i}>
          <line x1={x} y1={y + 16} x2={1320} y2={300} stroke={C.accent} strokeWidth={2.5} strokeDasharray="6 12" opacity={0.7} />
          <Satellite x={x} y={y} s={1.2} color={C.text} />
        </g>
      ))}
      <Phone x={1260} y={300} w={120} h={210} />
    </Svg>
    <div style={{position: 'absolute', left: 90, top: 180, width: 700}}>
      <div style={{fontSize: 132, fontWeight: 700, letterSpacing: -3, lineHeight: 1}}>SpoofNet</div>
      <div style={{fontSize: 40, color: C.text, marginTop: 34, lineHeight: 1.25}}>
        A ground-level map of GPS jamming and spoofing, from the phones already there.
      </div>
      <div style={{fontSize: 30, color: C.dim, marginTop: 34}}>Passive detection only. Research prototype.</div>
    </div>
  </AbsoluteFill>
);
