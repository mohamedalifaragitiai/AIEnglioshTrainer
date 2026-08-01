/** Downsample mono float samples to the 16 kHz PCM16 the server expects.
 *
 * Shared by Practice and Reading: both stream to the same socket, and two
 * copies of a resampler is two places for a rounding difference to hide.
 */
export function to16k(input: Float32Array, rate: number): ArrayBuffer {
  const ratio = rate / 16000;
  const n = Math.floor(input.length / ratio);
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}
