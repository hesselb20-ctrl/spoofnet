import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bars, C, Caption, Chip, FONT, MONO, Panel, Scene, Svg, ramp, rnd} from '../lib';

const BASE = [0.84, 0.5, 0.74, 0.62, 0.44, 0.8, 0.56, 0.7, 0.4, 0.66];

export const Spoofing: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const step = Math.floor(f / 8);
  const k = ramp(f, 66, 84);
  // Real signals differ by satellite; one transmitter delivers them all at one level.
  const bars = BASE.map((b, i) => b * (1 - k) + 0.72 * k + (rnd(`sp-${i}-${step}`) - 0.5) * (0.05 - 0.035 * k));
  const tx = 430, ty = 500;                  // where the phone is
  const fx = tx + 300 * k, fy = ty - 190 * k; // where the false signals say it is
  const offset = Math.round(1840 * k);
  const chips = ['Signals too alike', 'Position jump', 'Clock step', 'Constellations disagree'];
  return (
    <Scene f={f} dur={dur}>
      <Panel x={120} y={120} w={800} h={560} />
      <Panel x={1000} y={120} w={800} h={560} />
      <Svg>
        {Array.from({length: 7}, (_, i) => (
          <line key={`v${i}`} x1={200 + i * 110} y1={150} x2={200 + i * 110} y2={650} stroke={C.grid} strokeWidth={2} />
        ))}
        {Array.from({length: 5}, (_, i) => (
          <line key={`h${i}`} x1={150} y1={190 + i * 110} x2={890} y2={190 + i * 110} stroke={C.grid} strokeWidth={2} />
        ))}
        <path d="M150 600 C 300 540, 380 640, 520 590 S 760 520, 890 560 L 890 650 L 150 650 Z" fill="#132235" />
        <line x1={tx} y1={ty} x2={fx} y2={fy} stroke={C.spoof} strokeWidth={3} strokeDasharray="8 10" opacity={k} />
        <circle cx={tx} cy={ty} r={30} fill={C.accent} opacity={0.18} />
        <circle cx={tx} cy={ty} r={12} fill={C.accent} />
        <text x={tx} y={ty + 62} fill={C.text} fontSize={26} textAnchor="middle" fontFamily={FONT}>where the phone is</text>
        <text x={tx} y={ty + 94} fill={C.accent} fontSize={24} textAnchor="middle" fontFamily={FONT} opacity={ramp(f, 120, 136)}>
          Galileo still agrees
        </text>
        <g opacity={k}>
          <circle cx={fx} cy={fy} r={30} fill={C.spoof} opacity={0.2} />
          <circle cx={fx} cy={fy} r={12} fill={C.spoof} />
          <text x={fx} y={fy - 48} fill={C.text} fontSize={26} textAnchor="middle" fontFamily={FONT}>where GPS now says it is</text>
        </g>

        <text x={1044} y={186} fill={C.dim} fontSize={26} fontFamily={FONT}>Signal strength per satellite</text>
        <Bars x={1044} y={210} w={712} h={190} values={bars} color={k > 0.5 ? C.spoof : C.accent} />
        <text x={1044} y={470} fill={C.dim} fontSize={26} fontFamily={FONT}>Receiver clock offset</text>
        <text x={1756} y={470} fill={k > 0.5 ? C.spoof : C.text} fontSize={30} textAnchor="end" fontFamily={MONO}>
          {offset >= 0 ? '+' : ''}{offset.toLocaleString('en-US').replace(/,/g, ' ')} ns
        </text>
      </Svg>
      <div style={{position: 'absolute', left: 1044, top: 506, width: 712, display: 'flex', flexWrap: 'wrap', gap: 14}}>
        {chips.map((c, i) => (
          <div key={c} style={{opacity: ramp(f, 104 + i * 12, 118 + i * 12)}}>
            <Chip color={C.spoof}>{c}</Chip>
          </div>
        ))}
      </div>
      <div style={{position: 'absolute', left: 660, top: 140, opacity: ramp(f, 168, 184), transform: `scale(${ramp(f, 168, 186, 0.9, 1)})`}}>
        <Chip color={C.spoof} solid>Alarm: spoofing</Chip>
      </div>
      <Caption
        f={f}
        kicker="Spoofing"
        title="Fake signals leave fingerprints."
        sub="Too uniform, a jump in position or time, and constellations that no longer agree."
      />
    </Scene>
  );
};
