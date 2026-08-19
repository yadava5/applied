/**
 * Harness for driving the REAL `app/api/profile/avatar/route.ts` under
 * `node --test`, through the REAL `lib/supabase/server.ts` and the REAL
 * `lib/profile/avatar.ts`, with Supabase replaced at its own edge.
 *
 * Sibling of `helpers/callbackSession.mjs`, which does the same job for the two
 * PKCE handlers; the transpile-and-rewrite machinery is deliberately restated
 * here rather than shared, so that a change made for this route cannot alter
 * what the session tests are driving.
 *
 * WHY THE ROUTE AND NOT AN EXTRACTED FUNCTION. The guards this exists to
 * protect — the 512 KB ceiling, the byte-signature check, and the mapping from
 * "bucket not found" to a 501 — are written in the handler itself, in the order
 * they are written. A ports-shaped test over a lib function (the shape of
 * `account-delete-route.test.mjs`, which tests `lib/account/deletion.ts`) could
 * not see any of them being deleted, which is exactly how the handler came to
 * have 170 lines and no coverage: an audit removed the size guard and made the
 * route answer 502 unconditionally, and the whole suite stayed green.
 *
 * WHAT IS REAL AND WHAT IS STUBBED. Stubbed: `@supabase/ssr`'s
 * `createServerClient` (so no network and no live project) and `next/headers`'
 * `cookies()` (so there is no Next request scope to stand up). Real: the
 * factory in `lib/supabase/server.ts` including `applySessionHeaders`, the
 * route handler under test, `lib/profile/avatar.ts`'s rules, and Node's own
 * `FormData`/`Blob` — the multipart body is parsed by the same `Request` the
 * runtime parses it with, so "what arrived in the form" is not this file's
 * opinion.
 *
 * Every Storage and auth call the handler makes is recorded, because half of
 * what matters here is what the route did NOT do: a refusal that uploaded the
 * bytes first is a different bug from a refusal.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

// `lib/env.ts` validates at import time and `lib/supabase/server.ts` imports
// it. Never dialled — the Supabase client is stubbed — but they must parse.
process.env.NEXT_PUBLIC_SUPABASE_URL ??= "https://stub.supabase.co";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??= "stub-anon-key";

/** `apps/web` — what the `@/*` path alias in tsconfig.json points at. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../../..");

/** The signed-in account the handler meets: no photo yet, no Google identity. */
export const UID = "11111111-2222-4333-8444-555555555555";
export const SIGNED_IN = { id: UID, user_metadata: {} };

/** Supabase Storage's own wording for a bucket that was never created — the
 *  production state until `docs/avatars-bucket-2026-08-19.sql` is applied by
 *  hand. Spelled the way Storage spells it, not the way the app matches it. */
export const BUCKET_MISSING = { message: "Bucket not found" };

/** Any other Storage refusal. RLS is the realistic one: a path outside the
 *  caller's folder, or the policies not applied. */
export const STORAGE_REFUSED = { message: "new row violates row-level security policy" };

/** A PNG: the eight-byte magic, then padding to whatever length is asked for.
 *  Padding rather than noise because the sniff reads the head and the size
 *  guard reads the length, and a fixture should isolate the one under test. */
export function pngBytes(length = 64) {
  const bytes = new Uint8Array(length);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return bytes;
}

/** A WebP: `RIFF` … `WEBP`, the container the browser's canvas encodes to. */
export function webpBytes(length = 64) {
  const bytes = new Uint8Array(length);
  bytes.set([0x52, 0x49, 0x46, 0x46]);
  bytes.set([0x57, 0x45, 0x42, 0x50], 8);
  return bytes;
}

const dataModule = (source) =>
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;

// Both stubs read a hook off `globalThis` at call time rather than closing over
// test state: a `data:` URL module cannot share a binding with us.
const SSR_STUB = dataModule(
  "export function createServerClient(url, key, options) {" +
    "  return globalThis.__avatarSupabaseStub(url, key, options);" +
    "}",
);
const HEADERS_STUB = dataModule(
  "export async function cookies() { return globalThis.__avatarCookieStore; }",
);

function transpile(absPath, rewrite) {
  const { outputText } = ts.transpileModule(readFileSync(absPath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absPath,
  });
  return outputText.replace(
    /(\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/g,
    (_match, head, spec) => `${head}"${rewrite(spec)}"`,
  );
}

function localOrPackage(spec) {
  if (spec.startsWith("@/"))
    return pathToFileURL(resolvePath(WEB_ROOT, `${spec.slice(2)}.ts`)).href;
  // `next/server` has no ESM resolution without the extension under plain
  // `node --test`; Next's own bundler adds it.
  return import.meta.resolve(spec.startsWith("next/") ? `${spec}.js` : spec);
}

/** `lib/supabase/server.ts`, as a module URL, with only its two edges stubbed. */
const SERVER_MODULE = dataModule(
  transpile(resolvePath(WEB_ROOT, "lib/supabase/server.ts"), (spec) => {
    if (spec === "@supabase/ssr") return SSR_STUB;
    if (spec === "next/headers") return HEADERS_STUB;
    return localOrPackage(spec);
  }),
);

/** The real route handlers, wired to the real (stub-edged) server factory. */
const ROUTE = await import(
  dataModule(
    transpile(resolvePath(WEB_ROOT, "app/api/profile/avatar/route.ts"), (spec) =>
      spec === "@/lib/supabase/server" ? SERVER_MODULE : localOrPackage(spec),
    ),
  )
);

/** A `next/headers` cookie store that behaves like a Route Handler's: writes
 *  succeed. Nothing here writes one — the stubbed client never calls `setAll` —
 *  but the factory reads the store on the way in. */
const cookieJar = () => ({ getAll: () => [], set() {} });

/**
 * The Supabase client the handler is handed, plus the ledger of what it was
 * asked to do. `upload`, `remove` and `updateUser` answer with whatever error
 * the test names, defaulting to success.
 */
function supabaseStub({ user, uploadError, metaError, removeError }) {
  const calls = { upload: [], remove: [], updateUser: [] };
  const client = {
    auth: {
      async getUser() {
        return { data: { user }, error: null };
      },
      async updateUser(attributes) {
        calls.updateUser.push(attributes);
        return { data: { user }, error: metaError };
      },
    },
    storage: {
      from(bucket) {
        return {
          async upload(path, bytes, options) {
            calls.upload.push({ bucket, path, bytes, options });
            return { data: uploadError ? null : { path }, error: uploadError };
          },
          async remove(paths) {
            calls.remove.push({ bucket, paths });
            return { data: null, error: removeError };
          },
        };
      },
    },
  };
  return { client, calls };
}

async function run(invoke, options) {
  const { client, calls } = supabaseStub(options);
  globalThis.__avatarCookieStore = cookieJar();
  globalThis.__avatarSupabaseStub = () => client;
  try {
    const response = await invoke();
    return { response, status: response.status, body: await response.json(), calls };
  } finally {
    delete globalThis.__avatarCookieStore;
    delete globalThis.__avatarSupabaseStub;
  }
}

/**
 * `POST /api/profile/avatar` with a multipart body built the way the browser
 * builds it.
 *
 * `photo` is the raw bytes; `declaredType` is what the SENDER claims they are,
 * which is the thing the handler is not allowed to believe. `photo: null`
 * sends a text field under the same name instead — a request with no file.
 */
export async function postAvatar({
  user = SIGNED_IN,
  photo = pngBytes(),
  declaredType = "image/png",
  filename = "avatar.png",
  uploadError = null,
  metaError = null,
  removeError = null,
} = {}) {
  const { NextRequest } = await import("next/server.js");
  const form = new FormData();
  if (photo === null) form.append("photo", "not-a-file");
  else form.append("photo", new File([photo], filename, { type: declaredType }));

  const request = new NextRequest("https://applied.test/api/profile/avatar", {
    method: "POST",
    body: form,
  });
  return run(() => ROUTE.POST(request), { user, uploadError, metaError, removeError });
}

/** `DELETE /api/profile/avatar`. The handler takes no request. */
export async function deleteAvatar({
  user = SIGNED_IN,
  removeError = null,
  metaError = null,
} = {}) {
  return run(() => ROUTE.DELETE(), { user, uploadError: null, metaError, removeError });
}
