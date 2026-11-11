import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C, Caption, FONT, Scene, Svg, ramp} from '../lib';
// A copy of results/m6_flight.json: the detector's own output on the real flight log.
import flight from '../data/flight.json';

type Bin = {minute: number; cn0_top3_change_db: number; agc_change_db: number; adsb_low_accuracy_share: number | null};
const BINS = flight.track as Bin[];
const EVENT = flight.events[0] as {minute_start: number; minute_end: number};

const X0 = 330, X1 = 1740;
const x = (minute: number) => X0 + ((minute + 2.5) / 80) * (X1 - X0);   // bins are 5 minutes wide: plot at their centre
const row = (top: number, height: number, lo: number, hi: number) => (v: number) => top + ((hi - v) / (hi - lo)) * height;
const yCn0 = row(150, 170, -12, 3);
const yAgc = row(370, 130, -8, 2);
const yAir = row(550, 150, 0, 25);

const path = (ys: (v: number) => number, key: 'cn0_top3_change_db' | 'agc_change_db') =>
  BINS.map((b, i) => `${i ? 'L' : 'M'}${x(b.minute).toFixed(1)} ${ys(b[key]).toFixed(1)}`).join(' ');

export const Flight: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const drawn = ramp(f, 24, 130);
  const bars = (i: number) => ramp(f, 96 + i * 5, 120 + i * 5);
  const band = ramp(f, 150, 176);
  const label = (y: number, a: string, b: string) => (
    <g>
      <text x={120} y={y} fill={C.text} fontSize={26} fontWeight={600} fontFamily={FONT}>{a}</text>
      <text x={120} y={y + 32} fill={C.dim} fontSize={24} fontFamily={FONT}>{b}</text>
    </g>
  );
  return (
    <Scene f={f} dur={dur}>
      <Svg>
        <rect x={x(EVENT.minute_start - 2.5)} y={130} width={x(EVENT.minute_end - 2.5) - x(EVENT.minute_start - 2.5)} height={580}
          rx={14} fill={C.jam} opacity={0.16 * band} />
        <g opacity={band}>
          <rect x={x(51.4 - 2.5) - 190} y={96} width={380} height={50} rx={25} fill={C.jam} />
          <text x={x(51.4 - 2.5)} y={131} fill="#0b1017" fontSize={26} fontWeight={700} textAnchor="middle" fontFamily={FONT}>
            Detector: jamming event
          </text>
        </g>

        {label(214, 'Phone: signal', 'strongest satellites')}
        {label(420, 'Phone: gain', 'receiver AGC')}
        {label(612, 'Aircraft', 'reporting low accuracy')}

        {[yCn0(0), yAgc(0), yAir(0)].map((yy, i) => (
          <line key={i} x1={X0} y1={yy} x2={X1} y2={yy} stroke={C.line} strokeWidth={2} />
        ))}
        <clipPath id="draw"><rect x={X0 - 10} y={120} width={(X1 - X0 + 20) * drawn} height={420} /></clipPath>
        <g clipPath="url(#draw)" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path d={path(yCn0, 'cn0_top3_change_db')} stroke={C.accent} strokeWidth={6} />
          <path d={path(yAgc, 'agc_change_db')} stroke={C.ok} strokeWidth={6} />
          {BINS.map((b, i) => (
            <g key={i}>
              <circle cx={x(b.minute)} cy={yCn0(b.cn0_top3_change_db)} r={7} fill={C.accent} />
              <circle cx={x(b.minute)} cy={yAgc(b.agc_change_db)} r={7} fill={C.ok} />
            </g>
          ))}
        </g>
        <text x={X1 + 14} y={yCn0(-10) + 8} fill={C.accent} fontSize={24} fontFamily={FONT} opacity={drawn}>-10 dB</text>
        <text x={X1 + 14} y={yAgc(-6) + 8} fill={C.ok} fontSize={24} fontFamily={FONT} opacity={drawn}>-6 dB</text>

        {BINS.map((b, i) => {
          const share = b.adsb_low_accuracy_share;
          if (share === null) return null;
          const h = (yAir(0) - yAir(share * 100)) * bars(i);
          const hot = share >= 0.1;
          return (
            <g key={i}>
              <rect x={x(b.minute) - 30} y={yAir(0) - Math.max(h, 3)} width={60} height={Math.max(h, 3)} rx={6} fill={hot ? C.jam : '#55667c'} />
              {hot ? (
                <text x={x(b.minute)} y={yAir(share * 100) - 12} fill={C.text} fontSize={26} fontWeight={600} textAnchor="middle"
                  fontFamily={FONT} opacity={bars(i)}>
                  {`${Math.round(share * 100)}%`}
                </text>
              ) : null}
            </g>
          );
        })}

        <line x1={X0} y1={724} x2={X1} y2={724} stroke={C.line} strokeWidth={2} />
        <text x={x(10)} y={760} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT}>Riga, on the ground</text>
        <text x={x(49)} y={760} fill={C.text} fontSize={26} fontWeight={600} textAnchor="middle" fontFamily={FONT}>
          over Estonia and the Gulf of Finland
        </text>
        <text x={x(73)} y={760} fill={C.dim} fontSize={26} textAnchor="middle" fontFamily={FONT}>Tampere</text>
      </Svg>
      <Caption
        f={f}
        kicker="First real observation"
        title="One real flight, 22 March 2024: the phone's alarm lines up with the aircraft-based map."
        sub="One phone, one flight, at 8 km altitude. An observation, not yet a validation."
      />
    </Scene>
  );
};
