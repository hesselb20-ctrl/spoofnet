// Line-oriented H3 service: one JSON request per line on stdin, one JSON reply per line on stdout.
// Used by spoofnet/net/cells.py when the Python interpreter has no build of the h3 package.
'use strict';
const h3 = require('h3-js');
const readline = require('readline');

const ops = {
  cell: (q) => q.pts.map((p) => h3.latLngToCell(p[0], p[1], q.res)),
  center: (q) => q.cells.map((c) => h3.cellToLatLng(c)),
  boundary: (q) => q.cells.map((c) => h3.cellToBoundary(c)),
  disk: (q) => q.cells.map((c) => h3.gridDisk(c, q.k)),
  parent: (q) => q.cells.map((c) => h3.cellToParent(c, q.res)),
  res: (q) => q.cells.map((c) => h3.getResolution(c)),
  valid: (q) => q.cells.map((c) => h3.isValidCell(c)),
  distance: (q) => q.pairs.map((p) => {
    try { return h3.gridDistance(p[0], p[1]); } catch (e) { return -1; }
  }),
};

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let reply;
  try {
    const q = JSON.parse(line);
    if (!ops[q.op]) throw new Error('unknown op ' + q.op);
    reply = { ok: true, out: ops[q.op](q) };
  } catch (e) {
    reply = { ok: false, err: String(e) };
  }
  process.stdout.write(JSON.stringify(reply) + '\n');
});
