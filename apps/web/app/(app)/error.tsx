"use client";

export default function AppError({ reset }: { error: Error; reset: () => void }) {
  return (
    <section className="grid min-h-[50vh] place-items-center text-center">
      <div>
        <p className="label-mono">something broke</p>
        <h1 className="mt-2 text-2xl font-semibold text-strong">The board hit an error.</h1>
        <button
          type="button"
          onClick={reset}
          className="mt-4 rounded-lg border border-line px-4 py-2 text-sm text-foreground hover:border-line-strong"
        >
          Try again
        </button>
      </div>
    </section>
  );
}
