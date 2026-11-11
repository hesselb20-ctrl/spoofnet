import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bars, C, Caption, Chip, FONT, Meter, Panel, Scene, Svg, ramp, rnd} from '../lib';

const BASE = [0.84, 0.66, 0.76, 0.7, 0.58, 0.8, 0.62, 0.72, 0.54, 0.68];
// How much of each signal a roof takes away: very uneven, by direction.
const ROOF = [0.05, 0.72, 0.18, 0.86, 0.1, 0.55, 0.92, 0.08, 0.78, 0.3];

export const JamVsRoof: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const step = Math.floor(f / 8);
  const k = ramp(f, 62, 92);
  const jitter = (i: number, s: string) => (rnd(`${s}-${i}-${step}`) - 0.5) * 0.05;
  const jam = BASE.map((b, i) => b * (1 - 0.52 * k) + jitter(i, 'j'));
  const roof = BASE.map((b, i) => b * (1 - ROOF[i] * k) + jitter(i, 'r'));
  const note = (delay: number): React.CSSProperties => ({opacity: ramp(f, delay, delay + 14), fontSize: 28, color: C.dim, lineHeight: 1.35});
  const col = (x: number, title: string, color: string) => (
    <div style={{position: 'absolute', left: x + 44, top: 150, fontSize: 36, fontWeight: 650, color}}>{title}</div>
  );
  return (
    <Scene f={f} dur={dur}>
      <Panel x={120} y={120} w={800} h={560} />
      <Panel x={1000} y={120} w={800} h={560} />
      {col(120, 'Jamming', C.jam)}
      {col(1000, 'Under a roof, in a tunnel', C.text)}
      <Svg>
        <Bars x={164} y={226} w={712} h={190} values={jam} color={C.jam} />
        <Meter x={164} y={492} w={712} value={0.68 - 0.34 * k} label="Receiver gain" color={C.jam} />
        <Bars x={1044} y={226} w={712} h={190} values={roof} color={C.accent} />
        <Meter x={1044} y={492} w={712} value={0.68} label="Receiver gain" color={C.ok} />
      </Svg>
      <div style={{position: 'absolute', left: 164, top: 540, width: 712}}>
        <div style={note(110)}>Every satellite falls by the same amount.</div>
        <div style={note(126)}>Gain falls: extra power is in the band.</div>
      </div>
      <div style={{position: 'absolute', left: 1044, top: 540, width: 712}}>
        <div style={note(110)}>Some satellites fall, others do not.</div>
        <div style={note(126)}>Gain unchanged: nothing was added.</div>
      </div>
      <div style={{position: 'absolute', left: 650, top: 140, opacity: ramp(f, 160, 176), transform: `scale(${ramp(f, 160, 178, 0.9, 1)})`}}>
        <Chip color={C.jam} solid>Alarm: jamming</Chip>
      </div>
      <div style={{position: 'absolute', left: 1614, top: 140, opacity: ramp(f, 160, 176)}}>
        <Chip color={C.dim}>No alarm</Chip>
      </div>
      <div style={{position: 'absolute', left: 120, top: 706, fontSize: 27, color: C.dim, opacity: ramp(f, 196, 214), fontFamily: FONT}}>
        A phone with no gain reading cannot tell the two apart. It reports "unknown loss" instead of guessing.
      </div>
      <Caption
        f={f}
        kicker="Telling a jammer from a roof"
        title="A jammer lowers every satellite at once and pushes the receiver's gain down."
        sub="A roof blocks unevenly and adds no power."
      />
    </Scene>
  );
};
