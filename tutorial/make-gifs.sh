#!/usr/bin/env bash
# Cuts the five key scenes out of the rendered PNG sequence as looping GIFs for the README.
#
#   npm run frames          # first: PNG sequence into out/frames
#   bash make-gifs.sh       # then: GIFs into ../docs/media
#
# Each GIF stops before its scene fades out and holds the finished picture for
# a moment, so the loop reads as "build up, rest, again".
set -euo pipefail
cd "$(dirname "$0")"
OUT=../docs/media
FRAMES=out/frames/element-%04d.png

# name, first frame, last frame (scene starts and lengths are in src/Root.tsx)
SCENES=(
  "gap 0 196"
  "jamming 420 676"
  "spoofing 690 916"
  "network 1140 1396"
  "flight 1620 1906"
)

for row in "${SCENES[@]}"; do
  read -r name first last <<<"$row"
  chain="select='between(n,$first,$last)',setpts=N/FRAME_RATE/TB,fps=15,scale=800:-1:flags=lanczos,tpad=stop_mode=clone:stop_duration=2"
  ffmpeg -y -loglevel error -framerate 30 -i "$FRAMES" -vf "$chain,palettegen=max_colors=128:stats_mode=diff" out/palette-$name.png
  ffmpeg -y -loglevel error -framerate 30 -i "$FRAMES" -i out/palette-$name.png \
    -lavfi "$chain[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" -loop 0 "$OUT/$name.gif"
  echo "$name.gif $(wc -c <"$OUT/$name.gif") bytes"
done
