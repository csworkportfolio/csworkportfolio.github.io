// Encrypts a page payload for the password-locked pages, in the format main.js decrypts in the browser:
// PBKDF2-SHA256 (600,000 rounds) derives an AES-256-GCM key from the password.
// Reads {"password", "plaintext"} as JSON on stdin (never argv, so the password stays out of the process list)
// and prints {"v", "iter", "salt", "iv", "ct"} (base64) on stdout.
import { webcrypto as crypto } from "node:crypto";

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const { password, plaintext } = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const iter = 600000;
const salt = crypto.getRandomValues(new Uint8Array(16));
const iv = crypto.getRandomValues(new Uint8Array(12));
const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
const key = await crypto.subtle.deriveKey(
  { name: "PBKDF2", hash: "SHA-256", salt, iterations: iter },
  base, { name: "AES-GCM", length: 256 }, false, ["encrypt"],
);
const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(plaintext));
const b64 = (u) => Buffer.from(u).toString("base64");
process.stdout.write(JSON.stringify({ v: 1, iter, salt: b64(salt), iv: b64(iv), ct: b64(new Uint8Array(ct)) }));
