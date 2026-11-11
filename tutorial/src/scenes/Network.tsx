import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C, Caption, Chip, FONT, Scene, Svg, hexGrid, hexPoints, ramp} from '../lib';

const SRC = {x: 1010, y: 430};          // the true source, unknown to the network
const EST = {x: 1042, y: 408};          // what the network estimates
const R10 = 230;                        // pixels at which the loss is 10 dB
const PHONES = [
  [880, 360], [1120, 300], [1190, 470], [960, 560], [820, 500], [1080, 610], [740, 330], [1290, 236],
  [1340, 560], [640, 520], [1460, 260], [560, 280], [1520, 600], [420, 600], [1620, 420],
].map(([x, y]) => {
  const d = Math.hypot(x - SRC.x, y - SRC.y);
  return {x, y, drop: 10 * Math.log10(1 + 9 * (R10 / d) ** 2)};
});
const GRID = hexGrid(150, 150, 1770, 700, 62);

export const Network: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const on = ramp(f, 50, 80);
  const area = ramp(f, 118, 140);
  const est = ramp(f, 150, 176);
  const alarmed = PHONES.filter((p) => p.drop > 5).length;
  return (
    <Scene f={f} dur={dur}>
      <Svg>
        <clipPath id="netclip"><rect x={120} y={100} width={1680} height={650} rx={28} /></clipPath>
        <rect x={120} y={100} width={1680} height={650} rx={28} fill="#0e1620" stroke={C.line} strokeWidth={2} />
        <g clipPath="url(#netclip)">
        {GRID.map((h, i) => {
          const inside = PHONES.some((p) => p.drop > 5 && Math.hypot(p.x - h.x, p.y - h.y) < 62);
          return (
            <g key={i}>
              {inside ? <polygon points={hexPoints(h.x, h.y, 60)} fill={C.jam} opacity={0.22 * area} /> : null}
              <polygon points={hexPoints(h.x, h.y, 60)} fill="none" stroke={C.grid} strokeWidth={2} />
            </g>
          );
        })}
        {[0, 1, 2].map((i) => {
          const t = ((f - 50 + i * 30) % 90) / 90;
          return f > 50 ? (
            <circle key={i} cx={SRC.x} cy={SRC.y} r={40 + t * 520} fill="none" stroke={C.jam} strokeWidth={3} opacity={(1 - t) * 0.35 * on} />
          ) : null;
        })}
        {PHONES.map((p, i) => {
          const hit = p.drop > 5;
          const s = on * Math.min(p.drop, 22);
          return (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r={14 + s * 1.5} fill={hit ? C.jam : C.dim} opacity={hit ? 0.25 * on : 0} />
              <circle cx={p.x} cy={p.y} r={11} fill={hit && on > 0.5 ? C.jam : C.text} stroke={C.bg} strokeWidth={3} />
              {hit ? (
                <text x={p.x + 20} y={p.y - 14} fill={C.text} fontSize={26} fontWeight={600} fontFamily={FONT} opacity={ramp(f, 84, 100)}>
                  {`-${Math.round(p.drop)} dB`}
                </text>
              ) : null}
            </g>
          );
        })}
        </g>
        <g opacity={est}>
          <ellipse cx={EST.x} cy={EST.y} rx={118} ry={74} transform={`rotate(-24 ${EST.x} ${EST.y})`} fill={`${C.accent}18`}
            stroke={C.accent} strokeWidth={3} strokeDasharray="10 8" />
          <path d={`M${EST.x - 14} ${EST.y} H${EST.x + 14} M${EST.x} ${EST.y - 14} V${EST.y + 14}`} stroke={C.accent} strokeWidth={4} strokeLinecap="round" />
          <text x={EST.x + 132} y={EST.y - 66} fill={C.accent} fontSize={26} fontWeight={600} fontFamily={FONT}>estimated source,</text>
          <text x={EST.x + 132} y={EST.y - 34} fill={C.accent} fontSize={26} fontWeight={600} fontFamily={FONT}>with its uncertainty</text>
        </g>
      </Svg>
      <div style={{position: 'absolute', left: 150, top: 130, opacity: ramp(f, 186, 202), transform: `scale(${ramp(f, 186, 204, 0.92, 1)})`, transformOrigin: 'left top'}}>
        <Chip color={C.jam} solid>{`Incident: jamming, ${alarmed} phones`}</Chip>
      </div>
      <div style={{position: 'absolute', right: 150, top: 694, fontSize: 26, color: C.text, opacity: ramp(f, 206, 222), background: '#0b1017e6', padding: '6px 16px', borderRadius: 12}}>
        In simulation: an incident within about 6 seconds, source located to a median of 280 m.
      </div>
      <Caption
        f={f}
        kicker="Many phones"
        title="Three or more phones in one area make an incident."
        sub="Phones nearer the source lose more signal. That points to where it is."
      />
    </Scene>
  );
};
