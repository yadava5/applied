/* JobTracker classifier, in-browser.
 *
 * Faithful port of the 3-layer hybrid (backend/jobtracker/classifier):
 *   1. rules       — same 220 regexes, same scoring (strong +3 ×2-subject,
 *                    weak +1, negative −5, veto caps the category at 0),
 *                    same margin→confidence tiers, same ATS-domain boost.
 *                    Accept ≥0.9.
 *   2. embeddings  — cosine vs a synthetic example bank embedded with the
 *                    fine-tuned body ("query: " prefix). Accept ≥0.85.
 *   3. setfit      — LogisticRegression head over the same embedding
 *                    (no prefix). Accept ≥0.70, else needs_review.
 * The embedding body is the fine-tuned e5-small, dynamic-int8 ONNX,
 * verified output-identical to the Python pipeline (6/6 suite).
 */

import {
  NOISE_NEGATIVES,
  REFUTED_CONFIDENCE,
  ownTextRefutes,
  ownTextSpan,
  quoteSpokeForIt,
  reflowParagraphs,
  retractable,
  scoredBody,
  semanticRefutations,
  subjectWeights,
} from './preprocess.js';

/* THIS MODULE IS IMPORTABLE OUTSIDE A BROWSER, and that is a requirement
 * rather than a tidy-up (#955). Three things used to make `import('./app.js')`
 * impossible from Node, so the one port of this classifier with no test
 * anywhere was also the one the cross-engine differential could not add:
 *
 *   1. a top-level `import` from an `https:` URL, which Node's ESM loader
 *      refuses outright (`ERR_UNSUPPORTED_ESM_URL_SCHEME`);
 *   2. zero `export` statements, so there was nothing to import even with a
 *      loader that could reach it;
 *   3. `document.getElementById` at the top level.
 *
 * All three are gone: the model runtime is fetched lazily inside `boot`, the
 * rules layer is exported, and every DOM lookup happens inside `boot` — which
 * only runs when there is a document. `scripts/cross_engine_differential.py`
 * imports this file directly and scores it against the Python engine.
 */

const $ = (id) => document.getElementById(id);

/* Declared here and BOUND IN `boot`, never at module scope. Reading the
 * document while this file is being evaluated is blocker 3 above. */
let state = null, dot = null, go = null, prog = null, progbar = null;

let extractor = null, rules = null, head = null, examples = null;

/* ---------- layer 1: rules ---------- */
export function compileRules(raw) {
  const cats = {};
  for (const [cat, g] of Object.entries(raw.categories)) {
    cats[cat] = {
      strong: g.strong.map((p) => new RegExp(p, 'i')),
      weak: g.weak.map((p) => new RegExp(p, 'i')),
      negative: g.negative.map((p) => new RegExp(p, 'i')),
      // `assessment` and `follow_up` declare vetoes; the key is absent elsewhere.
      veto: (g.veto ?? []).map((p) => new RegExp(p, 'i')),
    };
  }
  return { cats, ats: raw.ats_domains };
}

/* Categories whose mail REPORTS on an application that already exists, as
 * opposed to `applied`, whose mail ASSERTS one into being. The port of
 * `rules.REPORTS_ON_AN_APPLICATION` (#451): a partition, not a ranking — a
 * report entails the assertion and the entailment does not run back. */
const REPORTS_ON_AN_APPLICATION = new Set(['rejection', 'interview', 'assessment', 'offer', 'pending_application']);

/* Compile a `rules.json` and install it as the one this module scores with.
 *
 * The browser calls this from `boot`; the differential calls it after reading
 * the same file off disk. Exported so an out-of-browser caller has a way in
 * that is not "reach into a module-local variable" — the compiled form is
 * what `rulesClassify` reads, and there must be exactly one of it. */
export function useRules(raw) {
  rules = compileRules(raw);
  // Derived from the compiled table rather than listed, so the split between a
  // genre filter and a semantic negative cannot rot away from the rules the
  // walk actually scores with.
  rules.refutations = semanticRefutations(rules.cats);
  rules.retractable = retractable(rules.cats);
  return rules;
}

export function rulesClassify(subject, rawBody, sender) {
  // THE BODY IS MASKED BEFORE ANY PATTERN SEES IT, exactly as
  // `RulesClassifier.classify` does it: quoted history removed, every
  // conditional clause cut from its marker to the end of its sentence, then
  // paragraphs reflowed. Until #955 this function scored the raw argument,
  // so a `rules.json` shared byte for byte with two engines that mask still
  // produced a different classifier here -- and the pattern arm #928 deleted
  // for being unreachable was reachable in this file alone.
  //
  // THE SUBJECT IS NOT MASKED, and that matches too: the engine transforms
  // the body and leaves the subject alone.
  const body = scoredBody(rawBody);

  // #441. A REPLY'S SUBJECT IS ABOUT THE THREAD, NOT ABOUT THIS MESSAGE. The
  // client copied that headline from a message someone else wrote weeks ago,
  // so "Re: Thank you for applying to X" is what the interview invitation, the
  // rejection and the scheduling note in that thread ALL look like. Demoted
  // below body weight rather than discarded.
  const [strongSubject, weakSubject] = subjectWeights(subject);

  // #417. The span above the quote, whether or not it clears the floor. When
  // it does not, the whole body -- quote included -- is what scored, so the
  // winner is the QUOTE's verdict rather than the sender's.
  const ownText = ownTextSpan(rawBody ?? '');
  const quoteSpoke = quoteSpokeForIt(ownText);

  const scores = {};
  let isAts = false;
  if (sender && sender.includes('@')) {
    const dom = sender.toLowerCase().split('@').pop();
    // Anchored the way `rules.is_ats_sender` is (#651): a listed domain or a
    // proper subdomain of one, never a host that merely contains the name.
    isAts = rules.ats.some((a) => dom === a || dom.endsWith(`.${a}`));
  }
  for (const [cat, g] of Object.entries(rules.cats)) {
    let s = 0;
    // Tracked separately from the score on purpose -- see the negative pass
    // below. A subject is a headline and is the cheapest part of a message to
    // make look like job mail; the body is what the message actually is.
    let hasStrongBody = false;
    for (const re of g.strong) {
      const inSubject = re.test(subject);
      const inBody = re.test(body);
      if (inBody) hasStrongBody = true;
      if (inSubject) s += strongSubject;
      else if (inBody) s += 3;
    }
    for (const re of g.weak) {
      if (re.test(subject)) s += weakSubject;
      else if (re.test(body)) s += 1;
    }
    for (const re of g.negative) {
      if (!(re.test(subject) || re.test(body))) continue;
      // #451. A GENRE FILTER MAY NOT OUTRANK A STRONG MATCH IN THE BODY. An
      // ATS confirmation that carries "manage preferences or unsubscribe" in
      // its footer is still a confirmation; a SEMANTIC negative -- job mail
      // saying otherwise -- still subtracts.
      if (hasStrongBody && NOISE_NEGATIVES.has(re.source)) continue;
      s -= 5;
    }
    for (const re of g.veto) { if (re.test(subject) || re.test(body)) s = Math.min(s, 0); }
    scores[cat] = s;
  }
  // Score first; at equal score a REPORT outranks an ASSERTION (#451) — a
  // report entails the assertion and not the reverse, so the tie is decided
  // by what the categories claim rather than by `rules.json`'s key order.
  // Margin, and therefore confidence, is unchanged: the scores are equal.
  const sorted = Object.entries(scores).sort(
    (a, b) =>
      b[1] - a[1] ||
      Number(REPORTS_ON_AN_APPLICATION.has(b[0])) - Number(REPORTS_ON_AN_APPLICATION.has(a[0])),
  );
  const [winner, ws] = sorted[0];
  const runner = sorted[1] ? sorted[1][1] : 0;
  if (ws <= 0) return { category: 'other', confidence: 0.5 };
  const margin = ws - runner;
  let conf = 0.6;
  if (ws >= 10 && margin >= 5) conf = 0.95;
  else if (ws >= 6 && margin >= 3) conf = 0.9;
  else if (ws >= 4 && margin >= 2) conf = 0.8;
  else if (ws >= 2 && margin >= 1) conf = 0.7;
  if (isAts && ['applied', 'rejection', 'interview', 'offer'].includes(winner))
    conf = Math.min(conf + 0.05, 0.95);
  // #417, last: when the quote did the talking and the sender's own words
  // argue against what it won with, the verdict is capped rather than
  // overturned. "We must withdraw the offer." over a quoted offer letter.
  if (quoteSpoke && ownTextRefutes(
        reflowParagraphs(ownText ?? ''), winner, rules.refutations, rules.retractable,
      ).length > 0) {
    conf = Math.min(conf, REFUTED_CONFIDENCE);
  }
  return { category: winner, confidence: conf };
}

/* ---------- embedding ---------- */
async function embed(text) {
  const out = await extractor(text, { pooling: 'mean', normalize: true });
  return Array.from(out.data);
}
const cosine = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0); // both normalized

/* ---------- layer 2: similarity ---------- */
function simClassify(vec) {
  let best = null, bestSim = -1;
  for (const ex of examples) {
    const s = cosine(vec, ex.vec);
    if (s > bestSim) { bestSim = s; best = ex.label; }
  }
  return { category: best, confidence: bestSim };
}

/* ---------- layer 3: setfit head ---------- */
function headClassify(vec) {
  const logits = head.coef.map((row, i) =>
    row.reduce((s, w, j) => s + w * vec[j], 0) + head.intercept[i]);
  const m = Math.max(...logits);
  const exps = logits.map((l) => Math.exp(l - m));
  const Z = exps.reduce((a, b) => a + b, 0);
  const probs = exps.map((e) => e / Z);
  const k = probs.indexOf(Math.max(...probs));
  return { category: head.classes[k], confidence: probs[k] };
}

/* ---------- UI ---------- */
const EXAMPLES = [
  ['Interview availability — SWE, Platform', "Hi Ayush, thanks for applying. We'd like to schedule a 45-minute technical interview next week. Could you share your availability?"],
  ['Your application was received', 'Thank you for applying to the Backend Engineer role. Our team is reviewing applications and will reach out if there is a match.'],
  ['Update on your application', "After careful consideration, we've decided to move forward with other candidates. We appreciate the time you invested."],
  ['Congratulations — offer details inside', "We're thrilled to extend an offer for the ML Engineer position. Compensation and start date are in the attached letter."],
  ['Next step: online assessment', 'Please complete the coding assessment linked below within 5 days. It should take about 90 minutes.'],
  ['Your weekly job digest', '12 new jobs recommended for you based on your profile. View all jobs or manage your preferences.'],
];

function renderTrace(rows) {
  $('trace').innerHTML = rows.map((r) =>
    `<div class="trow" data-state="${r.state}">
       <b>${r.layer}</b><span class="st">${r.note}</span>
       <span class="ms">${r.ms !== null ? r.ms.toFixed(1) + 'ms' : '—'}</span>
     </div>`).join('');
}

function renderVerdict(category, confidence, needsReview, source) {
  $('verdict').innerHTML =
    `<b>${category.replace(/_/g, ' ')}</b>
     <small>${(confidence * 100).toFixed(1)}% · answered by ${source}</small>
     ${needsReview ? '<small class="review">below 0.85 — production queues this for human review</small>' : ''}`;
}

async function classify() {
  const subject = $('subject').value.trim();
  const body = $('body').value.trim();
  if (!subject && !body) return;
  go.disabled = true;
  const trace = [];
  const t0 = performance.now();

  // layer 1 — rules
  const r1 = rulesClassify(subject, body, null);
  const t1 = performance.now();
  if (r1.confidence >= 0.9) {
    trace.push({ layer: 'rules', state: 'answered', note: `${r1.category} @ ${(r1.confidence * 100).toFixed(0)}% — regex answered`, ms: t1 - t0 });
    trace.push({ layer: 'embeddings', state: 'skipped', note: 'never ran', ms: null });
    trace.push({ layer: 'setfit', state: 'skipped', note: 'never ran', ms: null });
    renderVerdict(r1.category, r1.confidence, false, 'rules');
    renderTrace(trace); showTotal(t1 - t0); go.disabled = false; return;
  }
  trace.push({ layer: 'rules', state: 'passed', note: `top ${r1.category} @ ${(r1.confidence * 100).toFixed(0)}% — not confident enough`, ms: t1 - t0 });

  const text = `${subject} ${body}`.trim();

  // layer 2 — similarity (query-prefixed embedding)
  const tq0 = performance.now();
  const qvec = await embed('query: ' + text);
  const r2 = simClassify(qvec);
  const tq1 = performance.now();
  if (r2.confidence >= 0.85) {
    trace.push({ layer: 'embeddings', state: 'answered', note: `${r2.category} @ ${(r2.confidence * 100).toFixed(0)}% cosine`, ms: tq1 - tq0 });
    trace.push({ layer: 'setfit', state: 'skipped', note: 'never ran', ms: null });
    renderVerdict(r2.category, r2.confidence, false, 'embeddings');
    renderTrace(trace); showTotal(tq1 - t0); go.disabled = false; return;
  }
  trace.push({ layer: 'embeddings', state: 'passed', note: `best ${r2.category} @ ${(r2.confidence * 100).toFixed(0)}% — below 0.85`, ms: tq1 - tq0 });

  // layer 3 — setfit head (unprefixed embedding)
  const ts0 = performance.now();
  const svec = await embed(text);
  const r3 = headClassify(svec);
  const ts1 = performance.now();
  const needsReview = r3.confidence < 0.85;
  const category = r3.confidence >= 0.7 ? r3.category : 'needs_review';
  trace.push({ layer: 'setfit', state: 'answered', note: `${r3.category} @ ${(r3.confidence * 100).toFixed(0)}% softmax`, ms: ts1 - ts0 });
  renderVerdict(category, r3.confidence, needsReview, 'setfit');
  renderTrace(trace); showTotal(ts1 - t0); go.disabled = false;
}

function showTotal(ms) {
  $('timing').textContent = `total ${ms.toFixed(1)}ms · in this tab`;
}

async function boot() {
  state = $('state'); dot = $('dot'); go = $('go');
  prog = $('prog'); progbar = $('progbar');
  renderTrace([
    // No number until rules.json is actually loaded, and then the number is
    // COUNTED from it (see the re-render below). This line used to hard-code
    // "201 patterns, ready" while the file it describes carried 212: no claim
    // site in scripts/readme_facts.py can anchor a number inside a template
    // literal, so the gate that keeps every other copy honest could not see it.
    { layer: 'rules', state: 'passed', note: 'loading patterns', ms: null },
    { layer: 'embeddings', state: 'passed', note: 'awaiting model', ms: null },
    { layer: 'setfit', state: 'passed', note: 'awaiting model', ms: null },
  ]);
  $('examples').innerHTML = EXAMPLES.map(([s], i) =>
    `<button class="ghost" data-i="${i}">${s.slice(0, 34)}…</button>`).join('');
  $('examples').addEventListener('click', (e) => {
    const i = e.target?.dataset?.i;
    if (i === undefined) return;
    $('subject').value = EXAMPLES[i][0];
    $('body').value = EXAMPLES[i][1];
    if (!go.disabled) classify();
  });
  go.addEventListener('click', classify);

  const [rulesRaw, headRaw, exRaw] = await Promise.all([
    fetch('./rules.json').then((r) => r.json()),
    fetch('./head.json').then((r) => r.json()),
    fetch('./examples.json').then((r) => r.json()),
  ]);
  useRules(rulesRaw); head = headRaw; examples = exRaw;

  // The scored count, derived from the file the page just compiled — the same
  // definition scripts/readme_facts.py uses (strong + weak + negative; vetoes
  // score nothing and stay outside the total).
  const ruleCount = Object.values(rulesRaw.categories).reduce(
    (n, g) => n + g.strong.length + g.weak.length + g.negative.length, 0);
  renderTrace([
    { layer: 'rules', state: 'passed', note: `${ruleCount} patterns, ready`, ms: null },
    { layer: 'embeddings', state: 'passed', note: 'awaiting model', ms: null },
    { layer: 'setfit', state: 'passed', note: 'awaiting model', ms: null },
  ]);

  prog.hidden = false;
  // Fetched here rather than at the top of the file: a top-level `https:`
  // import makes this module unloadable outside a browser, and the rules layer
  // above needs no model at all.
  const { pipeline, env } = await import(
    'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.5.2'
  );
  env.allowRemoteModels = false;
  env.allowLocalModels = true;
  env.localModelPath = './';
  extractor = await pipeline('feature-extraction', 'model', {
    dtype: 'fp32',
    progress_callback: (p) => {
      if (p.status === 'progress' && p.total)
        progbar.style.width = `${Math.round((p.loaded / p.total) * 100)}%`;
    },
  });
  prog.hidden = true;

  await embed('warmup'); // JIT + session warm
  state.textContent = 'local · ready';
  dot.setAttribute('data-on', '');
  go.disabled = false;
}

if (typeof document !== 'undefined') {
  boot().catch((err) => {
    const state = $('state');
    if (state) state.textContent = 'failed to load';
    console.error(err);
  });
}
