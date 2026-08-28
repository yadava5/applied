/**
 * Structural (AST) primitives for asserting how a `.tsx` surface WIRES a shared
 * helper — not what the helper returns.
 *
 * WHY THIS EXISTS. `empty-subtitle.test.mjs` had four real behavioural tests
 * around `emptySubtitle`, and then one line of source-text `grep` to claim the
 * real dashboard actually uses it:
 *
 *     assert.match(page, /emptySubtitle\(\{/, "…builds its empty subtitle inline again");
 *
 * That is green if the page calls the helper with the wrong arguments, discards
 * what it returns, calls it in a branch that is never taken, or renders some
 * other string beside it (#550). A `grep` cannot see any of those, because none
 * of them changes the characters `emptySubtitle({`.
 *
 * WHAT THIS IS AND IS NOT. This parses the file and asks structural questions
 * of the tree: which properties does the call site pass, is the result bound,
 * does THAT binding reach the JSX attribute, is the call inside the branch the
 * empty board takes. It is a much stronger source check. It is still a source
 * check — nothing here executes the page. See the docstring on
 * `empty-subtitle.test.mjs` for exactly what remains ungated and why.
 *
 * HOW. `typescript` is already a devDependency (it is what `pnpm typecheck`
 * runs, and what `renderTsx.mjs` transpiles with), so this needs nothing new
 * installed. `ts.createSourceFile` with `setParentNodes: true` is what makes
 * the ancestor walks below possible — without it `node.parent` is undefined and
 * "is this call inside that branch?" cannot be answered at all.
 *
 * DELIBERATELY STRUCTURAL, NEVER `getText()` COMPARISONS. Matching the printed
 * text of a node is a regex wearing an AST costume, and it would reintroduce
 * the defect one layer down. `getText()` is used ONLY to build failure
 * messages, never to decide one.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

/** `apps/web`. This file sits at `tests/unit/helpers/`, so three levels up. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../../..");

/** Parse a `.tsx` file from `apps/web` into a tree with parent pointers. */
export function parseTsx(relativePath) {
  const absolute = resolvePath(WEB_ROOT, relativePath);
  return ts.createSourceFile(
    absolute,
    readFileSync(absolute, "utf8"),
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    ts.ScriptKind.TSX,
  );
}

/** The node's source text — for failure messages only, never for a decision. */
export function textOf(node) {
  return node.getText(node.getSourceFile()).replace(/\s+/g, " ");
}

/** Every node under `root` satisfying `predicate`, in source order. */
function collect(root, predicate) {
  const hits = [];
  const walk = (node) => {
    if (predicate(node)) hits.push(node);
    ts.forEachChild(node, walk);
  };
  walk(root);
  return hits;
}

/**
 * The LOCAL name a module's export is bound to in this file, or `null` when the
 * file does not import it as a value.
 *
 * WHY THE GATE NEEDS THIS. Every other check here is satisfied by any bare
 * identifier spelled `emptySubtitle`, so a file that DELETES the import and
 * defines its own inline `const emptySubtitle = …` passes all of them — while
 * being the exact defect this test file exists to prevent, wearing the shared
 * helper's name. Resolving the local name from the import first, and only then
 * looking for calls to it, closes that.
 *
 * `propertyName` is the EXPORTED name when the import is aliased
 * (`import { emptySubtitle as x }` -> propertyName `emptySubtitle`, name `x`),
 * and undefined otherwise, so both spellings resolve correctly rather than an
 * alias reading as a false red. Type-only imports do not count: they bind
 * nothing at runtime.
 */
export function importedLocalName(sourceFile, moduleSpecifier, exportName) {
  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement)) continue;
    if (!ts.isStringLiteral(statement.moduleSpecifier)) continue;
    if (statement.moduleSpecifier.text !== moduleSpecifier) continue;
    const clause = statement.importClause;
    if (clause === undefined || clause.isTypeOnly) continue;
    const bindings = clause.namedBindings;
    if (bindings === undefined || !ts.isNamedImports(bindings)) continue;
    for (const element of bindings.elements) {
      if (element.isTypeOnly) continue;
      if ((element.propertyName?.text ?? element.name.text) === exportName) return element.name.text;
    }
  }
  return null;
}

/**
 * Calls to a bare `name(…)` under `root`. Deliberately NOT `x.name(…)`: a
 * method that happens to share the name must not satisfy it. Pair this with
 * `importedLocalName` — on its own it cannot tell the shared helper from a
 * local one of the same name.
 */
export function callsTo(root, name) {
  return collect(
    root,
    (node) =>
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === name,
  );
}

/** `<Tag …>` and `<Tag … />` under `root`, as their opening elements. */
export function jsxElements(root, tagName) {
  return collect(
    root,
    (node) =>
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      ts.isIdentifier(node.tagName) &&
      node.tagName.text === tagName,
  );
}

/**
 * The call's single object-literal argument, or `null` when the call does not
 * have that shape. Callers assert on the null with their own message — every
 * lookup here returns null rather than throwing, so a moved call site reds as a
 * named assertion failure and not as a `TypeError` from the gate itself.
 */
export function objectArgument(call) {
  if (call.arguments.length !== 1) return null;
  const [argument] = call.arguments;
  return ts.isObjectLiteralExpression(argument) ? argument : null;
}

/**
 * `name -> value expression` for an object literal, or `null` if any property
 * is something this cannot read honestly: a spread (`...props`), a computed
 * name, a method or an accessor. Returning null there matters — a spread would
 * otherwise let an arbitrary set of arguments through a "the keys are exactly
 * these three" assertion.
 *
 * A shorthand's value IS its own name identifier, which is exactly right: it
 * reads the binding of that name.
 */
export function properties(object) {
  const found = new Map();
  for (const property of object.properties) {
    if (ts.isShorthandPropertyAssignment(property)) {
      found.set(property.name.text, property.name);
      continue;
    }
    if (!ts.isPropertyAssignment(property) || !ts.isIdentifier(property.name)) return null;
    found.set(property.name.text, property.initializer);
  }
  return found;
}

/**
 * Does this expression READ something, rather than state a constant?
 *
 * The mutation it exists for is `needsReview: state.needsReview` -> `needsReview: 0`:
 * the old grep survives that, and so does any "the keys are right" check. A
 * bare read (`x`, `x.y`, `x[0]`, `x!.y`) passes; a literal does not.
 */
export function readsABinding(expression) {
  let cursor = expression;
  while (
    ts.isPropertyAccessExpression(cursor) ||
    ts.isElementAccessExpression(cursor) ||
    ts.isNonNullExpression(cursor) ||
    ts.isParenthesizedExpression(cursor)
  ) {
    cursor = cursor.expression;
  }
  return ts.isIdentifier(cursor) && cursor.text !== "undefined";
}

/**
 * The name the call's result is bound to, or `null` when the result is
 * discarded. Walks out through the wrappers a call site legitimately sits
 * inside — the twin's `empty ? emptySubtitle(…) : buildSubtitle(…)` is a
 * conditional, not a bare initialiser.
 */
export function bindingFor(call) {
  let cursor = call.parent;
  while (
    cursor &&
    (ts.isConditionalExpression(cursor) ||
      ts.isParenthesizedExpression(cursor) ||
      ts.isAsExpression(cursor) ||
      ts.isSatisfiesExpression(cursor))
  ) {
    cursor = cursor.parent;
  }
  if (!cursor || !ts.isVariableDeclaration(cursor) || !ts.isIdentifier(cursor.name)) return null;
  return cursor.name.text;
}

/**
 * The identifier a JSX attribute is given, as in `subtitle={subtitle}` — or
 * `null` for anything else, INCLUDING `subtitle="literal"` and
 * `subtitle={"literal"}`. Both of those are the "renders a different string
 * beside it" mutation, and both are invisible to a grep for the call.
 */
export function attributeIdentifier(element, attributeName) {
  const attribute = element.attributes.properties.find(
    (property) =>
      ts.isJsxAttribute(property) &&
      ts.isIdentifier(property.name) &&
      property.name.text === attributeName,
  );
  if (attribute === undefined || attribute.initializer === undefined) return null;
  const { initializer } = attribute;
  if (!ts.isJsxExpression(initializer) || initializer.expression === undefined) return null;
  return ts.isIdentifier(initializer.expression) ? initializer.expression.text : null;
}

/**
 * The nearest `if` whose THEN branch contains this node, or `null` when the
 * node is not in one — which is precisely the "hoisted out of the empty
 * branch" mutation. The else side deliberately does not count.
 */
export function enclosingThenBranch(node) {
  let cursor = node;
  while (cursor.parent && !ts.isSourceFile(cursor.parent)) {
    const parent = cursor.parent;
    if (ts.isIfStatement(parent) && parent.thenStatement === cursor) return parent;
    cursor = parent;
  }
  return null;
}

/**
 * The nearest `cond ? … : …` whose TRUE arm contains this node, or `null`. The
 * twin branches with a conditional rather than an `if`, so this is its
 * equivalent of `enclosingThenBranch`. An inverted guard puts the call in
 * `whenFalse` and reds here.
 */
export function enclosingWhenTrue(node) {
  let cursor = node;
  while (cursor.parent && !ts.isSourceFile(cursor.parent)) {
    const parent = cursor.parent;
    if (ts.isConditionalExpression(parent) && parent.whenTrue === cursor) return parent;
    cursor = parent;
  }
  return null;
}

/**
 * Is this expression literally `state.total === 0` — the real page's empty-board
 * condition? Structural on every part, so `state.total === 1`,
 * `state.total !== 0` and `summary.total === 0` all read false.
 */
export function testsBoardIsEmpty(expression) {
  if (!ts.isBinaryExpression(expression)) return false;
  if (expression.operatorToken.kind !== ts.SyntaxKind.EqualsEqualsEqualsToken) return false;
  const { left, right } = expression;
  return (
    ts.isPropertyAccessExpression(left) &&
    ts.isIdentifier(left.expression) &&
    left.expression.text === "state" &&
    left.name.text === "total" &&
    ts.isNumericLiteral(right) &&
    right.text === "0"
  );
}

/** Is this expression exactly the identifier `name`? (`!name` reads false.) */
export function isIdentifierNamed(expression, name) {
  return ts.isIdentifier(expression) && expression.text === name;
}

/** A string literal with this exact value. */
export function isStringLiteral(expression, value) {
  return ts.isStringLiteral(expression) && expression.text === value;
}

/** The `false` keyword. */
export function isFalseLiteral(expression) {
  return expression.kind === ts.SyntaxKind.FalseKeyword;
}
