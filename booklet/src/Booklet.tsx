import React from "react";
import { PAGES, type PageSpec, type BodyKey } from "./manifest";
import { SECTION, SECTION_INK, COLORS, FONTS } from "./theme";

import { CoverPage } from "./templates/CoverPage";
import { BackCoverPage } from "./templates/BackCoverPage";
import { DividerPage } from "./primitives/DividerPage";
import { SpreadPage } from "./templates/SpreadPage";

import { EndpaperPage } from "./pages/EndpaperPage";
import { TocPage } from "./pages/TocPage";
import { WhyInboxPage } from "./pages/WhyInboxPage";
import { WhyLossyPage } from "./pages/WhyLossyPage";
import { WhySourcePage } from "./pages/WhySourcePage";
import { HowCascadePage } from "./pages/HowCascadePage";
import { HowRulesPage, HowEmbeddingsPage, HowSetfitPage } from "./pages/LayerDetailPages";
import { HowGatePage } from "./pages/HowGatePage";
import { InsideArchPage } from "./pages/InsideArchPage";
import { InsideOnnxPage } from "./pages/InsideOnnxPage";
import { InsideBrowserPage } from "./pages/InsideBrowserPage";
import { ProofF1Page } from "./pages/ProofF1Page";
import { ProofClassesPage } from "./pages/ProofClassesPage";
import { ProofTracePage } from "./pages/ProofTracePage";
import { ProofTestsPage } from "./pages/ProofTestsPage";
import { SecurityNoLlmPage } from "./pages/SecurityNoLlmPage";
import { SecurityOnDevicePage } from "./pages/SecurityOnDevicePage";
import { SecurityGmailPage } from "./pages/SecurityGmailPage";
import { BuildStackPage } from "./pages/BuildStackPage";
import { BuildClosingPage } from "./pages/BuildClosingPage";

/**
 * Group the flat page list into physical leaves, the way the bound book opens:
 * the cover alone on a recto, then verso+recto pairs, then the back cover alone
 * on a verso. Pairing from the cover instead (1-2, 3-4, …) would put every
 * `kind: "spread"` on two different leaves — the exact thing manifest.ts exists
 * to prevent — so the offset by one is load-bearing, not cosmetic.
 *
 * Screen only. In print each `.leaf` is `display: contents` (print.css), so
 * Puppeteer still sees a flat run of `.page` elements and paginates unchanged.
 */
function toLeaves(pages: readonly PageSpec[], twoUp: boolean): PageSpec[][] {
  const first = pages[0];
  const last = pages[pages.length - 1];
  if (!twoUp || pages.length < 3 || !first || !last) return pages.map((p) => [p]);
  const out: PageSpec[][] = [[first]];
  for (let i = 1; i < pages.length - 1; i += 2) {
    out.push(pages.slice(i, Math.min(i + 2, pages.length - 1)));
  }
  out.push([last]);
  return out.filter((leaf) => leaf.length > 0);
}

/** Subscribe to a media query. Two-up needs a real spread's width to exist. */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  React.useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/**
 * Top-level composer. Iterates `manifest.PAGES` in order and dispatches each
 * spec to its template. Every page renders as a `.page` block (print.css), so
 * Puppeteer paginates natively via `page-break-before: always`.
 *
 * On screen the pages are laid out as a left-to-right paged reader rather than
 * a vertical scroll: one leaf per snap point, two-up once the viewport is wide
 * enough for a full spread. See `useFitScale` for why the scale is capped at 1.
 */
export const Booklet: React.FC = () => {
  const twoUp = useMediaQuery("(min-width: 1760px)");
  const leaves = React.useMemo(() => toLeaves(PAGES, twoUp), [twoUp]);
  const scrollerRef = React.useRef<HTMLDivElement>(null);
  const [index, setIndex] = React.useState(0);
  useFitScale(scrollerRef, twoUp);

  const goTo = React.useCallback(
    (next: number) => {
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const clamped = Math.max(0, Math.min(next, scroller.children.length - 1));
      const leaf = scroller.children[clamped] as HTMLElement | undefined;
      if (!leaf) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      scroller.scrollTo({
        left: leaf.offsetLeft - (scroller.clientWidth - leaf.offsetWidth) / 2,
        behavior: reduce ? "auto" : "smooth",
      });
    },
    [],
  );

  // Track which leaf is centred, so the counter and the buttons agree with a
  // reader who navigated by swiping or by dragging the scrollbar.
  React.useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const mid = scroller.scrollLeft + scroller.clientWidth / 2;
        let best = 0;
        let bestDist = Infinity;
        Array.from(scroller.children).forEach((child, i) => {
          const el = child as HTMLElement;
          const dist = Math.abs(el.offsetLeft + el.offsetWidth / 2 - mid);
          if (dist < bestDist) {
            bestDist = dist;
            best = i;
          }
        });
        setIndex(best);
      });
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      scroller.removeEventListener("scroll", onScroll);
    };
  }, []);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        goTo(index + 1);
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        goTo(index - 1);
      } else if (e.key === "Home") {
        e.preventDefault();
        goTo(0);
      } else if (e.key === "End") {
        e.preventDefault();
        goTo(leaves.length - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goTo, index, leaves.length]);

  const shown = leaves[index] ?? [];
  const verso = shown[0];
  const recto = shown[1];
  const label = verso && recto ? `${verso.num}–${recto.num}` : String(verso?.num ?? 1);

  return (
    <>
      <div className="booklet-root" ref={scrollerRef}>
        {leaves.map((leaf, i) => (
          <div
            className="leaf"
            key={leaf[0]?.num ?? i}
            data-spread={leaf.length === 2 ? "true" : undefined}
          >
            <div className="leaf-inner">
              {leaf.map((p) => (
                <PageErrorBoundary key={p.num} pageNum={p.num}>
                  <PageSwitch spec={p} totalPages={PAGES.length} />
                </PageErrorBoundary>
              ))}
            </div>
          </div>
        ))}
      </div>

      <nav className="reader-bar" aria-label="Booklet pages">
        <button type="button" onClick={() => goTo(index - 1)} disabled={index === 0}>
          ‹<span className="sr-only"> Previous leaf</span>
        </button>
        <span className="reader-count tabular" aria-live="polite">
          {label} <span className="reader-of">/ {PAGES.length}</span>
        </span>
        <button
          type="button"
          onClick={() => goTo(index + 1)}
          disabled={index === leaves.length - 1}
        >
          ›<span className="sr-only"> Next leaf</span>
        </button>
      </nav>
    </>
  );
};

/**
 * Scale a leaf so it fits the window, and *never* enlarge past 1.
 *
 * The cap is not cosmetic. `scripts/clipcheck.mjs` measures the live screen
 * layout at an 840×1080 viewport — one leaf is 8.75in × 11.25in = 840×1080
 * CSS px there, so with the 48px/96px chrome insets the scale computes to
 * 0.911, the height term binding. The one-up leaf basis is what keeps the
 * factor near 1: scaling relative to the *spread* width instead would put
 * clipcheck at ~0.5 and silently halve every overflow threshold it checks.
 */
function useFitScale(ref: React.RefObject<HTMLDivElement | null>, twoUp: boolean) {
  React.useEffect(() => {
    const apply = () => {
      const scroller = ref.current;
      if (!scroller) return;
      const leafW = (twoUp ? 17.5 : 8.75) * 96;
      const leafH = 11.25 * 96;
      const scale = Math.min(
        1,
        (window.innerWidth - 48) / leafW,
        (window.innerHeight - 96) / leafH,
      );
      scroller.style.setProperty("--leaf-scale", String(Math.max(scale, 0.2)));
    };
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, [ref, twoUp]);
}

const BODY_COMPONENTS: Record<
  BodyKey,
  React.FC<{ parity: "recto" | "verso"; pageNumber: number; totalPages: number }>
> = {
  "why-inbox": WhyInboxPage,
  "why-lossy": WhyLossyPage,
  "why-source": WhySourcePage,
  "how-cascade": HowCascadePage,
  "how-rules": HowRulesPage,
  "how-embeddings": HowEmbeddingsPage,
  "how-setfit": HowSetfitPage,
  "how-gate": HowGatePage,
  "inside-architecture": InsideArchPage,
  "inside-onnx": InsideOnnxPage,
  "inside-browser": InsideBrowserPage,
  "proof-f1": ProofF1Page,
  "proof-classes": ProofClassesPage,
  "proof-trace": ProofTracePage,
  "proof-tests": ProofTestsPage,
  "sec-no-llm": SecurityNoLlmPage,
  "sec-on-device": SecurityOnDevicePage,
  "sec-gmail": SecurityGmailPage,
  "build-stack": BuildStackPage,
  "build-closing": BuildClosingPage,
};

const PageSwitch: React.FC<{ spec: PageSpec; totalPages: number }> = ({ spec, totalPages }) => {
  switch (spec.kind) {
    case "cover":
      return <CoverPage />;
    case "back-cover":
      return <BackCoverPage />;
    case "endpaper":
      return <EndpaperPage parity={spec.parity} pageNumber={spec.num} totalPages={totalPages} />;
    case "toc":
      return <TocPage parity={spec.parity} pageNumber={spec.num} totalPages={totalPages} />;
    case "divider":
      return (
        <DividerPage
          chapterNum={spec.chapterNum}
          chapterTitle={spec.chapterTitle}
          subtitle={spec.subtitle}
          color={SECTION[spec.sectionKey]}
          sectionKey={spec.sectionKey}
          chapterIndex={spec.chapterIndex}
          chapterTotal={spec.chapterTotal}
        />
      );
    case "spread":
      return (
        <SpreadPage
          half={spec.half}
          parity={spec.parity}
          pageNumber={spec.num}
          totalPages={totalPages}
          sectionLabel="BUILD"
          sectionColor={SECTION_INK["06_BUILD"]}
        />
      );
    case "body": {
      const Component = BODY_COMPONENTS[spec.body];
      return <Component parity={spec.parity} pageNumber={spec.num} totalPages={totalPages} />;
    }
    default: {
      const _never: never = spec;
      void _never;
      return null;
    }
  }
};

/**
 * Per-page error boundary — isolates a render failure to one page so the PDF
 * pipeline keeps going and the offending page is visible rather than blank.
 */
class PageErrorBoundary extends React.Component<
  { pageNum: number; children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <section
          className="page"
          style={{ background: COLORS.PAPER, padding: 48, fontFamily: FONTS.MONO, fontSize: 11, color: COLORS.DANGER }}
        >
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Page {this.props.pageNum} render failed</div>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 9 }}>{String(this.state.error.message)}</pre>
        </section>
      );
    }
    return this.props.children;
  }
}
