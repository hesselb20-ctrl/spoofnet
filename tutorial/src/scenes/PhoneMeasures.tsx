import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bars, C, Caption, FONT, MONO, Meter, Panel, Phone, Satellite, Scene, Svg, ramp, rnd} from '../lib';

const LABELS = ['G05', 'G13', 'G27', 'E11', 'E24', 'R07', 'R18', 'C21', 'C34'];
const BASE = [0.82, 0.64, 0.74, 0.7, 0.56, 0.6, 0.48, 0.77, 0.52];

export const PhoneMeasures: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const step = Math.floor(f / 8);
  const values = BASE.map((b, i) => b + (rnd(`pm-${i}-${step}`) - 0.5) * 0.09);
  const sats = LABELS.map((_, i) => {
    const a = Math.PI * (1.08 + (0.84 * i) / (LABELS.length - 1));
    return {x: 520 + 380 * Math.cos(a), y: 600 + 440 * Math.sin(a)};
  });
  const px = 520;
  const py = 420;
  const clock = (1794300000 + f / 30).toFixed(2);
  return (
    <Scene f={f} dur={dur}>
      <Svg>
        {sats.map((s, i) => {
          const on = ramp(f, 14 + i * 5, 30 + i * 5);
          return (
            <g key={i} opacity={on}>
              <line x1={s.x} y1={s.y + 14} x2={px} y2={py} stroke={C.accent} strokeWidth={2.5} strokeDasharray="6 12"
                strokeDashoffset={-f * 1.6} opacity={0.25 + 0.6 * values[i]} />
              <Satellite x={s.x} y={s.y} />
            </g>
          );
        })}
        <Phone x={px - 95} y={py} w={190} h={330}>
          <text x={px} y={py + 150} fill={C.text} fontSize={30} fontWeight={600} textAnchor="middle" fontFamily={FONT}>listening</text>
          <text x={px} y={py + 190} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT}>never sending</text>
        </Phone>
      </Svg>

      <Panel x={1040} y={120} w={760} h={630} style={{opacity: ramp(f, 40, 60)}} />
      <Svg>
        <g opacity={ramp(f, 46, 66)}>
          <text x={1090} y={184} fill={C.text} fontSize={32} fontWeight={600} fontFamily={FONT}>Reported every second</text>
          <text x={1090} y={236} fill={C.dim} fontSize={26} fontFamily={FONT}>Signal strength per satellite</text>
          <Bars x={1090} y={262} w={660} h={210} values={values} labels={LABELS} />
          <Meter x={1090} y={590} w={660} value={0.66 + (rnd(`agc-${step}`) - 0.5) * 0.03} label="Receiver gain (AGC)" />
          <text x={1090} y={688} fill={C.dim} fontSize={26} fontFamily={FONT}>Receiver clock</text>
          <text x={1750} y={688} fill={C.text} fontSize={28} textAnchor="end" fontFamily={MONO}>{clock} s</text>
        </g>
      </Svg>
      <Caption
        f={f}
        kicker="The idea"
        title="Every Android phone already measures the satellites it hears."
        sub="Signal strength per satellite, receiver gain and clock. No extra hardware."
      />
    </Scene>
  );
};
