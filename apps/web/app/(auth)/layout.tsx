import type { ReactNode } from "react";

/**
 * The signed-out shell: one centred column over the auth scene's emerald
 * bloom (`.auth-scene`, globals.css) — the closing act's atmosphere restated
 * for the pages where a visitor arrives. The column width is the form's own
 * measure; the pages render their content directly into it.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-scene">
      <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-12">
        {children}
      </main>
    </div>
  );
}
