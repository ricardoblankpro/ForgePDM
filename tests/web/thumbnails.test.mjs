import test from "node:test";
import assert from "node:assert/strict";
import {createHash, webcrypto} from "node:crypto";
import {validatedThumbnail} from "../../src/forgepdm/web/api.mjs";

globalThis.crypto ??= webcrypto;
const source = "a".repeat(64);
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8N8AAAAASUVORK5CYII=", "base64");
function response(bytes=png, changes={}) {
  return new Response(bytes, {headers:{"Content-Type":"image/png", "X-ForgePDM-Source-Hash":source,
    "X-Content-SHA256":createHash("sha256").update(bytes).digest("hex"), ...changes}});
}
test("preview validates exact source and image hash before display", async()=>{
  const image=await validatedThumbnail(response(),source);
  assert.equal(image.type,"image/png");
  assert.deepEqual(Buffer.from(await image.arrayBuffer()),png);
});
test("preview rejects wrong source, corrupt hash and non-PNG responses", async()=>{
  await assert.rejects(validatedThumbnail(response(),"b".repeat(64)));
  await assert.rejects(validatedThumbnail(response(png,{"X-Content-SHA256":"0".repeat(64)}),source));
  await assert.rejects(validatedThumbnail(response(png,{"Content-Type":"text/html"}),source));
});
test("preview rejects dishonest sizes and oversized dimensions", async()=>{
  await assert.rejects(validatedThumbnail(response(Buffer.alloc(1024*1024+1)),source));
  const oversized=Buffer.from(png); oversized.writeUInt32BE(513,16);
  await assert.rejects(validatedThumbnail(response(oversized),source));
});
