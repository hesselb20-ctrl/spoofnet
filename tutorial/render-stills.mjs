// Renders the README images: the banner and one still per scene.
//
//   node render-stills.mjs [output folder]        default: ../docs/media
//
// Set BROWSER_EXECUTABLE to a Chrome Headless Shell binary if the bundled one cannot start
// (on Windows that happens when the project sits in a path longer than 260 characters).
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(process.argv[2] ?? path.join(here, '..', 'docs', 'media'));
const browserExecutable = process.env.BROWSER_EXECUTABLE || undefined;

// Scene lengths must match SCENES in src/Root.tsx. Each still is taken 25 frames before its scene ends.
const scenes = [
  ['gap', 210], ['phone', 210], ['jamming', 270], ['spoofing', 240], ['privacy', 210],
  ['network', 270], ['map', 210], ['flight', 300], ['status', 240],
];

const serveUrl = await bundle({entryPoint: path.join(here, 'src', 'index.ts')});
const tutorial = await selectComposition({serveUrl, id: 'Tutorial', browserExecutable});
const poster = await selectComposition({serveUrl, id: 'Poster', browserExecutable});

await renderStill({composition: poster, serveUrl, output: path.join(outDir, 'banner.png'), browserExecutable});
console.log('banner.png');
let start = 0;
for (const [i, [id, dur]] of scenes.entries()) {
  const name = `${String(i + 1).padStart(2, '0')}-${id}.png`;
  await renderStill({composition: tutorial, serveUrl, frame: start + dur - 25, output: path.join(outDir, name), browserExecutable});
  console.log(name);
  start += dur;
}
