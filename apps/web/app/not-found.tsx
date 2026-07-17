import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="label-mono">404</p>
      <h1 className="text-3xl font-medium tracking-tight text-strong">
        Nothing is filed under this address.
      </h1>
      <Link
        href="/"
        className="mt-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
      >
        ← back to the landing
      </Link>
    </main>
  );
}
