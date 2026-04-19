import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * `cn` — merge Tailwind utility classes with conflict resolution.
 *
 * This is the standard shadcn/ui helper. Kept here so generated components
 * (via `pnpm dlx shadcn@latest add ...`) import from `@/lib/utils` as
 * configured in `components.json`.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
