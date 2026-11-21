/**
 * Serves release artifacts out of the R2 bucket.
 *
 * The bucket's r2.dev host does not answer for this account, and Pages caps a
 * static file at 25 MiB, so downloads are proxied through here instead.
  */
interface Env {
  DOWNLOADS: R2Bucket;
}

const TYPES: Record<string, string> = {
  dmg: "application/x-apple-diskimage",
  exe: "application/vnd.microsoft.portable-executable",
  zip: "application/zip",
  gz: "application/gzip",
  json: "application/json",
};

export const onRequest: PagesFunction<Env> = async ({ params, env }) => {
  const path = Array.isArray(params.path) ? params.path.join("/") : String(params.path ?? "");
  if (!path) return new Response("not found", { status: 404 });

  const object = await env.DOWNLOADS.get(path);
  if (!object) return new Response("not found", { status: 404 });

  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const filename = path.split("/").pop() ?? "download";

  return new Response(object.body, {
    headers: {
      "content-type": TYPES[ext] ?? "application/octet-stream",
      "content-length": String(object.size),
      "content-disposition": `attachment; filename="${filename}"`,
      "cache-control": "public, max-age=86400",
      etag: object.httpEtag,
    },
  });
};
