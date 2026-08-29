/**
 * Mount a real component tree, click it, and read what it drew.
 *
 * WHY THIS EXISTS, and it is not "nicer tests". The filed ledger's correction
 * control asks "which application is this about?" only when three separate
 * things line up: the ledger hands the control its employer's board rows, the
 * reader opens the control, and the stage they pick is a lifecycle answer. Every
 * one of those is a runtime fact, and none of them was executed by anything in
 * CI. The line was held by a regex over the source instead, and a regex reads
 * intent:
 *
 *     FiledMailList:      reviewCandidates(m, board) -> reviewCandidates(m, board.slice(0, 1))
 *     ReclassifyControl:  const showPicker = ...     -> const showPicker = false
 *
 * Both silence the question permanently. Both left `pnpm test:unit`, `tsc` and
 * `eslint` green, and both still matched the tripwire's own pattern. Reading
 * source is also how #560 was misdiagnosed in the first place. So the question
 * is now asserted by putting it on a screen and looking for it.
 *
 * WHY NOT PLAYWRIGHT. The only surface that mounts this control over a real
 * board is the signed-in `/inbox`, and every session-gated e2e test in this
 * repo skips — see `tests/e2e/session.ts`: both e2e jobs boot against a
 * placeholder Supabase project, so those tests have never executed, not once. A
 * gate there would be dead coverage wearing a green tick, which is the exact
 * defect class this file is closing.
 *
 * WHAT IS REAL HERE AND WHAT IS NOT. The components are the real ones, loaded
 * from source through `appModule.mjs`'s hooks — no stubs, no copies, no
 * test-only props. React and `react-dom/client` are the real ones. The DOM is
 * jsdom, and the App Router context is a stub object whose methods do nothing.
 * That stub is the honest limit of this file: it can tell you what a component
 * DREW and what it did when you clicked it, and it cannot tell you what
 * `router.refresh()` would have re-rendered. It also cannot manufacture the
 * question — a router that does nothing cannot put a legend on the page — so
 * an assertion that the question appeared is not an assertion about the stub.
 * Layout, CSS and navigation stay Playwright's.
 *
 * `helpers/renderTsx.mjs` is the smaller neighbour and is still the right tool
 * for a leaf component with no hooks: it needs no DOM and no cleanup.
 */
import { register } from "node:module";
import { after } from "node:test";
import { resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { JSDOM } from "jsdom";

register("./appModuleHooks.mjs", import.meta.url);

/** `apps/web`, from `tests/unit/helpers/`. */
const WEB_ROOT = resolvePath(fileURLToPath(import.meta.url), "../../../..");

// The DOM has to exist BEFORE `react-dom/client` is evaluated, so both are set
// up here at module load rather than inside `mount`.
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost/",
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;
globalThis.Event = dom.window.Event;
globalThis.MouseEvent = dom.window.MouseEvent;
// `next/link` reaches for `self` (via `requestIdleCallback`), not `window`.
globalThis.self = dom.window;
// `navigator` is a getter-only property on the Node global object.
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
// Makes React's `act` do its work synchronously and warn about updates that
// escape it, instead of leaving state changes to a scheduler nothing awaits.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const React = await import("react");
const { createRoot } = await import("react-dom/client");
const { AppRouterContext } = await import(
  "next/dist/shared/lib/app-router-context.shared-runtime.js"
);

export { React };

/** Import an app module — including a `.tsx` one — by path relative to `apps/web`. */
export function importApp(relativePath) {
  return import(pathToFileURL(resolvePath(WEB_ROOT, relativePath)).href);
}

/**
 * Every App Router method a component might call, doing nothing.
 *
 * Named and complete rather than a Proxy: a missing method should fail loudly
 * as a missing method, and the list is what says which navigations this file
 * cannot observe.
 */
const INERT_ROUTER = {
  refresh() {},
  push() {},
  replace() {},
  back() {},
  forward() {},
  prefetch() {},
};

/**
 * Render `element` into a fresh container and hand back a small reader.
 *
 * Unmounts itself after the test file, so a suite of these does not leave a
 * dozen React roots attached to one document.
 */
export async function mount(element) {
  const container = dom.window.document.createElement("div");
  dom.window.document.body.appendChild(container);
  const root = createRoot(container);
  await React.act(async () => {
    root.render(React.createElement(AppRouterContext.Provider, { value: INERT_ROUTER }, element));
  });

  const view = {
    /** Everything the tree drew, for a `match` on copy the user reads. */
    html: () => container.innerHTML,
    query: (selector) => container.querySelector(selector),
    queryAll: (selector) => Array.from(container.querySelectorAll(selector)),
    /** Click, and settle whatever state that click set. */
    click: async (target) => {
      const node = typeof target === "string" ? view.query(target) : target;
      if (!node) throw new Error(`mountApp: nothing to click for ${String(target)}`);
      await React.act(async () => {
        node.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
      });
    },
    /**
     * Choose an <option> the way a user does.
     *
     * Assigned through the prototype's setter because React installs its own
     * `value` property on the element and reads the previous value off it to
     * decide whether anything changed — a plain `select.value = x` is seen as
     * a no-op and the `onChange` handler never runs.
     */
    choose: async (target, value) => {
      const node = typeof target === "string" ? view.query(target) : target;
      if (!node) throw new Error(`mountApp: no <select> for ${String(target)}`);
      const setValue = Object.getOwnPropertyDescriptor(
        dom.window.HTMLSelectElement.prototype,
        "value",
      ).set;
      await React.act(async () => {
        setValue.call(node, value);
        node.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
    },
    unmount: async () => {
      await React.act(async () => root.unmount());
      container.remove();
    },
  };

  after(() => {
    container.remove();
  });
  return view;
}
