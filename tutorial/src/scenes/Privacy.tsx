import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C, Caption, FONT, MONO, Phone, Scene, Svg, ramp} from '../lib';

const TRACK = 'M0 250 C 30 200, 70 230, 80 170 S 40 110, 90 80 S 150 60, 140 10';

export const Privacy: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const draw = ramp(f, 16, 70);
  const go = ramp(f, 84, 138);
  const cardX = 620 + (930 - 620) * go;
  return (
    <Scene f={f} dur={dur}>
      <Svg>
        <Phone x={260} y={130} w={300} h={560}>
          <g transform="translate(336 230)">
            <path d={TRACK} fill="none" stroke={C.accent} strokeWidth={5} strokeLinecap="round" pathLength={1}
              strokeDasharray={1} strokeDashoffset={1 - draw} />
            <circle cx={0} cy={250} r={8} fill={C.accent} />
          </g>
          <text x={410} y={560} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT}>raw measurements</text>
          <text x={410} y={596} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT}>positions, tracks</text>
          <g transform="translate(410 640)" opacity={ramp(f, 60, 76)}>
            <rect x={-17} y={-6} width={34} height={26} rx={5} fill={C.ok} />
            <path d="M-10 -6 V-16 A10 10 0 0 1 10 -16 V-6" fill="none" stroke={C.ok} strokeWidth={5} />
          </g>
        </Phone>
        <text x={410} y={742} fill={C.ok} fontSize={30} fontWeight={600} textAnchor="middle" fontFamily={FONT}>Stays on the phone</text>

        <line x1={600} y1={410} x2={1300} y2={410} stroke={C.line} strokeWidth={3} strokeDasharray="4 12" />
        <path d="M1290 396 L1316 410 L1290 424" fill="none" stroke={C.line} strokeWidth={3} />

        <rect x={1340} y={250} width={340} height={320} rx={26} fill={C.panel} stroke={C.line} strokeWidth={2} />
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <rect x={1376} y={292 + i * 84} width={268} height={58} rx={12} fill="#182331" />
            <circle cx={1404} cy={321 + i * 84} r={7} fill={i === 0 ? C.ok : C.dim} />
          </g>
        ))}
        <text x={1510} y={626} fill={C.text} fontSize={30} fontWeight={600} textAnchor="middle" fontFamily={FONT}>Aggregation server</text>
        <text x={1510} y={666} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT}>never sees a track</text>

        <g transform={`translate(${cardX} 330)`} opacity={ramp(f, 80, 92)}>
          <rect x={0} y={0} width={380} height={160} rx={18} fill="#0f1620" stroke={C.accent} strokeWidth={2.5} />
          {[['type', 'jam'], ['cell', 'coarse map cell'], ['score', '0.97']].map(([k, v], i) => (
            <g key={k}>
              <text x={24} y={48 + i * 42} fill={C.dim} fontSize={26} fontFamily={MONO}>{k}</text>
              <text x={130} y={48 + i * 42} fill={C.text} fontSize={26} fontFamily={MONO}>{v}</text>
            </g>
          ))}
        </g>
        <text x={1120} y={552} fill={C.accent} fontSize={30} fontWeight={600} textAnchor="middle" fontFamily={FONT} opacity={ramp(f, 96, 112)}>
          Leaves the phone
        </text>
        <text x={1120} y={592} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT} opacity={ramp(f, 104, 120)}>
          an event, a coarse cell, a score
        </text>
      </Svg>
      <Caption
        f={f}
        kicker="Privacy by construction"
        title="Detection runs on the phone."
        sub="Only events and coarse map cells are uploaded. Tracks never leave it."
      />
    </Scene>
  );
};
