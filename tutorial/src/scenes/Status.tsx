import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C, FONT, Mark, Panel, Scene, ramp} from '../lib';

const ROWS = [
  {done: true, text: 'Detection, network and map work in software replay'},
  {done: true, text: 'One real observation, on a public flight log'},
  {done: false, text: 'Not yet validated at ground or sea level'},
  {done: false, text: 'Phone app written, not yet built or field-tested'},
];

export const Status: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  return (
    <Scene f={f} dur={dur}>
      <div style={{position: 'absolute', left: 120, top: 110, fontSize: 26, fontWeight: 600, letterSpacing: 3, textTransform: 'uppercase',
        color: C.accent, opacity: ramp(f, 6, 20)}}>
        Where it stands, November 2026
      </div>
      <div style={{position: 'absolute', left: 120, top: 180, width: 980}}>
        {ROWS.map((r, i) => (
          <div key={r.text} style={{display: 'flex', alignItems: 'center', gap: 26, marginBottom: 44,
            opacity: ramp(f, 20 + i * 22, 36 + i * 22), transform: `translateX(${ramp(f, 20 + i * 22, 40 + i * 22, -24, 0)}px)`}}>
            <Mark done={r.done} size={56} />
            <div style={{fontSize: 40, fontWeight: 550, lineHeight: 1.2, color: r.done ? C.text : C.dim}}>{r.text}</div>
          </div>
        ))}
      </div>
      <Panel x={1180} y={180} w={620} h={400} style={{opacity: ramp(f, 116, 134), transform: `scale(${ramp(f, 116, 138, 0.96, 1)})`}}>
        <div style={{padding: '70px 56px'}}>
          <div style={{fontSize: 62, fontWeight: 700, letterSpacing: -0.5}}>Passive only.</div>
          <div style={{fontSize: 36, color: C.dim, marginTop: 26, lineHeight: 1.35}}>It listens.<br />It never transmits.</div>
        </div>
      </Panel>
      <div style={{position: 'absolute', left: 120, top: 760, opacity: ramp(f, 150, 168)}}>
        <div style={{fontSize: 86, fontWeight: 700, letterSpacing: -1.5, fontFamily: FONT}}>SpoofNet</div>
        <div style={{fontSize: 36, color: C.dim, marginTop: 6}}>
          A ground-level map of GPS jamming and spoofing, from the phones already there.
        </div>
        <div style={{fontSize: 32, color: C.accent, marginTop: 22}}>github.com/hesselb20-ctrl/spoofnet</div>
      </div>
    </Scene>
  );
};
