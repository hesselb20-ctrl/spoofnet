# The explainer video and the README images, as code

Everything in `docs/media/` is rendered from this folder: the 72-second
explainer, the banner and one still per scene. Nothing is drawn by hand, so a
change to the product story is a change to a few lines of TSX and a re-render.

It is built with [Remotion](https://www.remotion.dev/) (React components
rendered frame by frame). Remotion has its own licence, free for individuals
and small teams and paid for larger companies; check it before commercial use.

## Scenes

`src/Root.tsx` lists them in order with their lengths (30 frames per second).

| Scene | File | Says |
|---|---|---|
| The gap | `scenes/Gap.tsx` | Interference maps are built from aircraft; the ground is blank |
| The idea | `scenes/PhoneMeasures.tsx` | Phones already measure every satellite they hear |
| Jamming | `scenes/JamVsRoof.tsx` | How a jammer differs from a roof, and what a phone without gain data does |
| Spoofing | `scenes/Spoofing.tsx` | The fingerprints of fake signals |
| Privacy | `scenes/Privacy.tsx` | What stays on the phone and what leaves it |
| Many phones | `scenes/Network.tsx` | Incidents and source localisation |
| The map | `scenes/MapView.tsx` | No data is never drawn as clean |
| Real observation | `scenes/Flight.tsx` | The one real flight, from `src/data/flight.json` |
| Status | `scenes/Status.tsx` | What is done and what is not |

`src/data/flight.json` holds the `events` and `track` parts of
`results/m6_flight.json`, the detector's own output on the real flight log.
The numbers quoted on screen ("6 seconds", "280 m") come from
`results/m5_network.json` and are labelled as simulation.

## Render

Needs Node.js 18 or newer and ffmpeg.

```bash
npm install
npm run studio                       # preview and scrub in the browser
node render-stills.mjs               # banner and stills into ../docs/media
npm run frames                       # PNG sequence into out/frames
ffmpeg -y -framerate 30 -i out/frames/element-%04d.png \
  -vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p" \
  -c:v libx264 -crf 18 -preset slow -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -movflags +faststart ../docs/media/spoofnet-tutorial.mp4
```

The frames are rendered as PNG and encoded by ffmpeg, with the colour matrix
set explicitly, so that the dark background keeps its exact colour.

On Windows, if the project sits in a folder whose path is longer than 260
characters, the bundled browser cannot start. Copy
`node_modules/.remotion/chrome-headless-shell/...` to a short path and pass it
with `--browser-executable=<path>` (for the stills script: the
`BROWSER_EXECUTABLE` environment variable).

## Rules for changes

* Every claim on screen must be true of the repository on the day of the render.
  Replay results are labelled as simulation; the flight is labelled as one
  observation.
* Nothing here shows or explains transmitting equipment. Interference appears
  only as what a receiver observes.
* Text in the graphics stays at 26 px or larger so the stills read at README width.
