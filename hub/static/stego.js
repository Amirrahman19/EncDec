"use strict";
/* Stego core (steganography + AES-GCM), shared with the phone web app.
   Pure functions: no DOM access. UI can set hooks.log / hooks.progress. */

const hooks = { log() {}, progress() {} };
function log(msg) { hooks.log(msg); }
function setProgress(f, label) { hooks.progress(f, label); }
function yieldToUI() { return new Promise((r) => setTimeout(r, 0)); }

const HEADER_BITS = 32;

function bytesToBits(bytes) {
  const bits = new Uint8Array(bytes.length * 8);
  let idx = 0;
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i];
    for (let j = 7; j >= 0; j--) bits[idx++] = (b >> j) & 1;
  }
  return bits;
}

function bitsToBytes(bits) {
  const out = new Uint8Array(Math.floor(bits.length / 8));
  for (let i = 0; i < out.length; i++) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i * 8 + j];
    out[i] = byte;
  }
  return out;
}

function packPayload(bytes) {
  const len = bytes.length;
  const out = new Uint8Array(4 + bytes.length);
  out[0] = (len >>> 24) & 0xff;
  out[1] = (len >>> 16) & 0xff;
  out[2] = (len >>> 8) & 0xff;
  out[3] = len & 0xff;
  out.set(bytes, 4);
  return out;
}

function unpackLength(headerBytes) {
  return ((headerBytes[0] << 24) | (headerBytes[1] << 16) | (headerBytes[2] << 8) | headerBytes[3]) >>> 0;
}


/* ---------------------------------------------------------------------- */
/* Optional password encryption: AES-256-GCM + PBKDF2-HMAC-SHA256         */
/* Blob: "SGE1" | salt(16) | nonce(12) | ciphertext+tag  (same as desktop) */
/* ---------------------------------------------------------------------- */

const MAGIC = new Uint8Array([0x53, 0x47, 0x45, 0x31]); // "SGE1"
const KDF_ITERATIONS = 200000;

function requireCrypto() {
  if (!window.crypto || !crypto.subtle) {
    throw new Error("Encryption needs a secure context. Open this file directly from your phone's storage (file://) or over https — not over plain http:// on a network address.");
  }
}

async function deriveKey(password, salt) {
  requireCrypto();
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: KDF_ITERATIONS, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

async function encryptBytes(data, password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(password, salt);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData: MAGIC }, key, data));
  const out = new Uint8Array(4 + 16 + 12 + ct.length);
  out.set(MAGIC, 0); out.set(salt, 4); out.set(nonce, 20); out.set(ct, 32);
  return out;
}

async function decryptBytes(blob, password) {
  if (blob.length < 4 + 16 + 12 + 16) throw new Error("Encrypted data is truncated.");
  const key = await deriveKey(password, blob.slice(4, 20));
  try {
    return new Uint8Array(await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: blob.slice(20, 32), additionalData: MAGIC }, key, blob.slice(32)));
  } catch (e) {
    throw new Error("Wrong password, or the data was altered/corrupted.");
  }
}

function hasMagic(b) { return b.length >= 4 && b[0] === 0x53 && b[1] === 0x47 && b[2] === 0x45 && b[3] === 0x31; }

async function sealBytes(data, password) { return password ? encryptBytes(data, password) : data; }

async function openBytes(data, password) {
  if (!hasMagic(data)) return data;
  if (!password) throw new Error("This content is password-protected. Enter the password.");
  return decryptBytes(data, password);
}

async function openText(data, password) {
  const plain = await openBytes(data, password);
  try { return new TextDecoder("utf-8", { fatal: true }).decode(plain); }
  catch (e) { throw new Error("No readable hidden message found in this file."); }
}

function bytesToB64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function b64ToBytes(str) {
  let bin;
  try { bin = atob(str.replace(/\s+/g, "")); } catch (e) { throw new Error("That doesn't look like an encrypted message (bad base64)."); }
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function encryptText(message, password) {
  if (!password) throw new Error("A password is required for text encryption.");
  return bytesToB64(await encryptBytes(new TextEncoder().encode(message), password));
}

async function decryptText(token, password) {
  if (!password) throw new Error("A password is required to decrypt.");
  const blob = b64ToBytes(token);
  if (!hasMagic(blob)) throw new Error("That doesn't look like an encrypted message from this tool.");
  return new TextDecoder().decode(await decryptBytes(blob, password));
}

/* ---------------------------------------------------------------------- */
/* WAV parsing / writing (16/8/32-bit PCM, mono or multi-channel)         */
/* ---------------------------------------------------------------------- */

function parseWav(arrayBuffer) {
  const dv = new DataView(arrayBuffer);
  if (dv.getUint32(0, false) !== 0x52494646) throw new Error("Not a RIFF/WAV file.");
  if (dv.getUint32(8, false) !== 0x57415645) throw new Error("Not a WAVE file.");
  let offset = 12;
  let fmt = null, dataOffset = -1, dataLength = 0;
  while (offset + 8 <= arrayBuffer.byteLength) {
    const id = String.fromCharCode(dv.getUint8(offset), dv.getUint8(offset+1), dv.getUint8(offset+2), dv.getUint8(offset+3));
    const size = dv.getUint32(offset + 4, true);
    const body = offset + 8;
    if (id === "fmt ") {
      fmt = {
        audioFormat: dv.getUint16(body, true),
        numChannels: dv.getUint16(body + 2, true),
        sampleRate: dv.getUint32(body + 4, true),
        byteRate: dv.getUint32(body + 8, true),
        blockAlign: dv.getUint16(body + 12, true),
        bitsPerSample: dv.getUint16(body + 14, true),
      };
    } else if (id === "data") {
      dataOffset = body;
      dataLength = size;
    }
    offset = body + size + (size % 2);
  }
  if (!fmt || dataOffset < 0) throw new Error("Invalid WAV file: missing fmt or data chunk.");
  if (![8, 16, 32].includes(fmt.bitsPerSample)) throw new Error(`Unsupported bits-per-sample: ${fmt.bitsPerSample}`);
  const dataBuf = arrayBuffer.slice(dataOffset, dataOffset + dataLength);
  let samples;
  if (fmt.bitsPerSample === 8) samples = new Uint8Array(dataBuf);
  else if (fmt.bitsPerSample === 16) samples = new Int16Array(dataBuf);
  else samples = new Int32Array(dataBuf);
  return { fmt, samples };
}

function writeWav(fmt, samples) {
  const bytesPerSample = fmt.bitsPerSample / 8;
  const dataLength = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataLength);
  const dv = new DataView(buffer);
  function writeStr(off, str) { for (let i = 0; i < str.length; i++) dv.setUint8(off + i, str.charCodeAt(i)); }
  writeStr(0, "RIFF");
  dv.setUint32(4, 36 + dataLength, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); // PCM
  dv.setUint16(22, fmt.numChannels, true);
  dv.setUint32(24, fmt.sampleRate, true);
  dv.setUint32(28, fmt.byteRate, true);
  dv.setUint16(32, fmt.blockAlign, true);
  dv.setUint16(34, fmt.bitsPerSample, true);
  writeStr(36, "data");
  dv.setUint32(40, dataLength, true);
  new Uint8Array(buffer, 44).set(new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength));
  return buffer;
}

function embedBitsIntoSamples(samples, bits) {
  for (let i = 0; i < bits.length; i++) samples[i] = (samples[i] & ~1) | bits[i];
}

/* ---------------------------------------------------------------------- */
/* Image helpers (RGB-only, alpha untouched — matches desktop's 3-channel */
/* layout so files stay cross-compatible with the desktop tool)           */
/* ---------------------------------------------------------------------- */

function blobToDataURL(blob) {
  // data: URIs work for both display and <a download> regardless of the
  // page's origin. blob: object URLs are blocked for downloads on Android
  // Chrome when the page is opened via file:// (opaque/null origin) —
  // that's the "URL needs to be http or https" error — so data: URIs are
  // used everywhere instead of URL.createObjectURL.
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function loadImageFile(file) {
  return new Promise(async (resolve, reject) => {
    try {
      const dataUrl = await blobToDataURL(file);
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("Could not load image file."));
      img.src = dataUrl;
    } catch (e) {
      reject(e);
    }
  });
}

function imageToCanvas(img) {
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  // Opaque backdrop: canvas stores premultiplied alpha, which would silently
  // corrupt the RGB LSBs of any transparent/semi-transparent pixel.
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);
  return canvas;
}

function flattenRGB(imageData) {
  const { data, width, height } = imageData;
  const pixelCount = width * height;
  const flat = new Uint8Array(pixelCount * 3);
  for (let p = 0, j = 0; p < pixelCount; p++) {
    flat[j++] = data[p * 4 + 0];
    flat[j++] = data[p * 4 + 1];
    flat[j++] = data[p * 4 + 2];
  }
  return flat;
}

function writeFlatRGBBack(imageData, flat) {
  const { data, width, height } = imageData;
  const pixelCount = width * height;
  for (let p = 0, j = 0; p < pixelCount; p++) {
    data[p * 4 + 0] = flat[j++];
    data[p * 4 + 1] = flat[j++];
    data[p * 4 + 2] = flat[j++];
  }
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/png"));
}

function blobToArrayBuffer(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsArrayBuffer(blob);
  });
}

/* ---------------------------------------------------------------------- */
/* Core operations                                                        */
/* ---------------------------------------------------------------------- */

async function encodeMessageInImage(file, message, password) {
  log(`Loading image: ${file.name}`);
  setProgress(0.05, "Loading image...");
  const img = await loadImageFile(file);
  const canvas = imageToCanvas(img);
  const ctx = canvas.getContext("2d");
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const flat = flattenRGB(imageData);

  const payload = packPayload(await sealBytes(new TextEncoder().encode(message), password));
  const bits = bytesToBits(payload);
  log(`Payload size: ${payload.length} bytes (${bits.length} bits)`);
  if (bits.length > flat.length) {
    throw new Error(`Message too large for this image. Capacity: ${Math.floor(flat.length/8)} bytes, needed: ${Math.floor(bits.length/8)} bytes.`);
  }

  setProgress(0.3, "Embedding bits...");
  for (let i = 0; i < flat.length; i++) if (i < bits.length) flat[i] = (flat[i] & 0xfe) | bits[i];
  await yieldToUI();

  writeFlatRGBBack(imageData, flat);
  ctx.putImageData(imageData, 0, 0);
  setProgress(0.8, "Encoding PNG...");
  const blob = await canvasToPngBlob(canvas);
  setProgress(1.0, "Done.");
  log("Encode complete.");
  return blob;
}

async function decodeMessageFromImage(file, password) {
  log(`Loading image: ${file.name}`);
  setProgress(0.1, "Loading image...");
  const img = await loadImageFile(file);
  const canvas = imageToCanvas(img);
  const ctx = canvas.getContext("2d");
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const flat = flattenRGB(imageData);

  setProgress(0.4, "Reading header...");
  const headerBits = new Uint8Array(HEADER_BITS);
  for (let i = 0; i < HEADER_BITS; i++) headerBits[i] = flat[i] & 1;
  const length = unpackLength(bitsToBytes(headerBits));
  log(`Header reports payload length: ${length} bytes`);

  const totalBits = HEADER_BITS + length * 8;
  if (totalBits > flat.length) throw new Error("Image does not contain a valid embedded message.");

  setProgress(0.7, "Extracting payload...");
  const payloadBits = new Uint8Array(length * 8);
  for (let i = 0; i < payloadBits.length; i++) payloadBits[i] = flat[HEADER_BITS + i] & 1;
  const data = bitsToBytes(payloadBits);
  setProgress(1.0, "Done.");
  log("Decode complete.");
  return await openText(data, password);
}

async function encodeMessageInAudio(file, message, password) {
  log(`Loading audio: ${file.name}`);
  setProgress(0.05, "Loading audio...");
  const buf = await blobToArrayBuffer(file);
  const { fmt, samples } = parseWav(buf);
  log(`WAV: ${fmt.numChannels}ch, ${fmt.sampleRate}Hz, ${fmt.bitsPerSample}-bit`);

  const payload = packPayload(await sealBytes(new TextEncoder().encode(message), password));
  const bits = bytesToBits(payload);
  log(`Payload size: ${payload.length} bytes (${bits.length} bits)`);
  if (bits.length > samples.length) {
    throw new Error(`Message too large for this audio file. Capacity: ${Math.floor(samples.length/8)} bytes, needed: ${Math.floor(bits.length/8)} bytes.`);
  }

  setProgress(0.4, "Embedding bits...");
  embedBitsIntoSamples(samples, bits);
  await yieldToUI();

  setProgress(0.85, "Writing WAV...");
  const outBuf = writeWav(fmt, samples);
  setProgress(1.0, "Done.");
  log("Encode complete.");
  return new Blob([outBuf], { type: "audio/wav" });
}

async function decodeMessageFromAudio(file, password) {
  log(`Loading audio: ${file.name}`);
  setProgress(0.1, "Loading audio...");
  const buf = await blobToArrayBuffer(file);
  const { fmt, samples } = parseWav(buf);
  log(`WAV: ${fmt.numChannels}ch, ${fmt.sampleRate}Hz, ${fmt.bitsPerSample}-bit`);

  setProgress(0.4, "Reading header...");
  const headerBits = new Uint8Array(HEADER_BITS);
  for (let i = 0; i < HEADER_BITS; i++) headerBits[i] = samples[i] & 1;
  const length = unpackLength(bitsToBytes(headerBits));
  log(`Header reports payload length: ${length} bytes`);

  const totalBits = HEADER_BITS + length * 8;
  if (totalBits > samples.length) throw new Error("Audio file does not contain a valid embedded message.");

  setProgress(0.7, "Extracting payload...");
  const payloadBits = new Uint8Array(length * 8);
  for (let i = 0; i < payloadBits.length; i++) payloadBits[i] = samples[HEADER_BITS + i] & 1;
  const data = bitsToBytes(payloadBits);
  setProgress(1.0, "Done.");
  log("Decode complete.");
  return await openText(data, password);
}

async function encodeImageInAudio(imageFile, audioFile, password) {
  log(`Loading image: ${imageFile.name}`);
  setProgress(0.05, "Loading image...");
  const img = await loadImageFile(imageFile);
  const canvas = imageToCanvas(img);
  const pngBlob = await canvasToPngBlob(canvas);
  const pngBytes = new Uint8Array(await blobToArrayBuffer(pngBlob));
  log(`Encoded image to PNG: ${pngBytes.length} bytes`);

  log(`Loading audio: ${audioFile.name}`);
  setProgress(0.15, "Loading audio...");
  const buf = await blobToArrayBuffer(audioFile);
  const { fmt, samples } = parseWav(buf);
  log(`WAV: ${fmt.numChannels}ch, ${fmt.sampleRate}Hz, ${fmt.bitsPerSample}-bit`);

  const payload = packPayload(await sealBytes(pngBytes, password));
  const bits = bytesToBits(payload);
  log(`Payload size: ${payload.length} bytes (${bits.length} bits)`);
  if (bits.length > samples.length) {
    throw new Error(`Image too large for this audio file. Capacity: ${Math.floor(samples.length/8)} bytes, needed: ${Math.floor(bits.length/8)} bytes. Try a smaller image or longer audio.`);
  }

  setProgress(0.4, "Embedding bits...");
  embedBitsIntoSamples(samples, bits);
  await yieldToUI();

  setProgress(0.85, "Writing WAV...");
  const outBuf = writeWav(fmt, samples);
  setProgress(1.0, "Done.");
  log("Encode complete.");
  return new Blob([outBuf], { type: "audio/wav" });
}

async function decodeImageFromAudio(audioFile, password) {
  log(`Loading audio: ${audioFile.name}`);
  setProgress(0.1, "Loading audio...");
  const buf = await blobToArrayBuffer(audioFile);
  const { fmt, samples } = parseWav(buf);
  log(`WAV: ${fmt.numChannels}ch, ${fmt.sampleRate}Hz, ${fmt.bitsPerSample}-bit`);

  setProgress(0.3, "Reading header...");
  const headerBits = new Uint8Array(HEADER_BITS);
  for (let i = 0; i < HEADER_BITS; i++) headerBits[i] = samples[i] & 1;
  const length = unpackLength(bitsToBytes(headerBits));
  log(`Header reports payload length: ${length} bytes`);

  const totalBits = HEADER_BITS + length * 8;
  if (totalBits > samples.length) throw new Error("Audio file does not contain a valid embedded image.");

  setProgress(0.6, "Extracting payload...");
  const payloadBits = new Uint8Array(length * 8);
  for (let i = 0; i < payloadBits.length; i++) payloadBits[i] = samples[HEADER_BITS + i] & 1;
  const data = bitsToBytes(payloadBits);
  setProgress(1.0, "Done.");
  log("Decode complete.");
  return new Blob([await openBytes(data, password)], { type: "image/png" });
}

/* ---------------------------------------------------------------------- */

/* ---------------------------------------------------------------------- */
/* Live chat crypto: per-room key from passphrase, fresh nonce per message */
/* Message: base64( nonce(12) | AES-GCM ciphertext ), AAD = room name      */
/* ---------------------------------------------------------------------- */

async function deriveChatKey(passphrase, room) {
  requireCrypto();
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: new TextEncoder().encode("stego-chat:" + room), iterations: KDF_ITERATIONS, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

async function chatEncrypt(key, room, text) {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce, additionalData: new TextEncoder().encode(room) }, key, new TextEncoder().encode(text)));
  const out = new Uint8Array(12 + ct.length);
  out.set(nonce, 0); out.set(ct, 12);
  return bytesToB64(out);
}

async function chatDecrypt(key, room, b64) {
  const raw = b64ToBytes(b64);
  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: raw.slice(0, 12), additionalData: new TextEncoder().encode(room) }, key, raw.slice(12));
  return new TextDecoder().decode(pt);
}
