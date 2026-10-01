// Writes build/icon.png (256x256) for the installer/exe, matching the ring
// icon the app draws at runtime. Run with: npm run icon
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const SIZE = 256;
const [R, G, B] = [46, 170, 140];

const c = (SIZE - 1) / 2;
const outer = SIZE / 2 - 0.5;
const inner = outer * 0.55;
const raw = Buffer.alloc(SIZE * (SIZE * 4 + 1));
for (let y = 0; y < SIZE; y++) {
  const row = y * (SIZE * 4 + 1);
  raw[row] = 0; // filter: none
  for (let x = 0; x < SIZE; x++) {
    const d = Math.hypot(x - c, y - c);
    const a = Math.max(0, Math.min(1, outer - d + 0.5)) * Math.max(0, Math.min(1, d - inner + 0.5));
    const i = row + 1 + x * 4;
    raw[i] = R;
    raw[i + 1] = G;
    raw[i + 2] = B;
    raw[i + 3] = Math.round(a * 255);
  }
}

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let k = n;
  for (let j = 0; j < 8; j++) k = k & 1 ? 0xedb88320 ^ (k >>> 1) : k >>> 1;
  return k >>> 0;
});
const crc32 = (buf) => {
  let crc = 0xffffffff;
  for (const byte of buf) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
};
const chunk = (type, data) => {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
};

const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(SIZE, 0);
ihdr.writeUInt32BE(SIZE, 4);
ihdr[8] = 8; // bit depth
ihdr[9] = 6; // RGBA
const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk('IHDR', ihdr),
  chunk('IDAT', zlib.deflateSync(raw)),
  chunk('IEND', Buffer.alloc(0)),
]);

const out = path.join(__dirname, '..', 'build', 'icon.png');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, png);
console.log('wrote', out);
