import React from 'react';
import {AbsoluteFill, Composition, Sequence} from 'remotion';
import {C, FPS, H, W} from './lib';
import {Poster} from './Poster';
import {Flight} from './scenes/Flight';
import {Gap} from './scenes/Gap';
import {JamVsRoof} from './scenes/JamVsRoof';
import {MapView} from './scenes/MapView';
import {Network} from './scenes/Network';
import {PhoneMeasures} from './scenes/PhoneMeasures';
import {Privacy} from './scenes/Privacy';
import {Spoofing} from './scenes/Spoofing';
import {Status} from './scenes/Status';

// The whole film: one row per scene, in order. Lengths are in frames at 30 fps.
export const SCENES = [
  {id: 'gap', dur: 210, C: Gap},
  {id: 'phone', dur: 210, C: PhoneMeasures},
  {id: 'jamming', dur: 270, C: JamVsRoof},
  {id: 'spoofing', dur: 240, C: Spoofing},
  {id: 'privacy', dur: 210, C: Privacy},
  {id: 'network', dur: 270, C: Network},
  {id: 'map', dur: 210, C: MapView},
  {id: 'flight', dur: 300, C: Flight},
  {id: 'status', dur: 240, C: Status},
];
export const TOTAL = SCENES.reduce((n, s) => n + s.dur, 0);

const Tutorial: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill style={{backgroundColor: C.bg}}>
      {SCENES.map((s) => {
        const start = from;
        from += s.dur;
        return (
          <Sequence key={s.id} from={start} durationInFrames={s.dur} name={s.id}>
            <s.C dur={s.dur} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

export const Root: React.FC = () => (
  <>
    <Composition id="Tutorial" component={Tutorial} durationInFrames={TOTAL} fps={FPS} width={W} height={H} />
    <Composition id="Poster" component={Poster} durationInFrames={1} fps={FPS} width={1600} height={800} />
  </>
);
