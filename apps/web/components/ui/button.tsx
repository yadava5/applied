import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Minimal shadcn/ui-compatible Button.
 *
 * Shape matches what `pnpm dlx shadcn@latest add button` would generate so
 * that later, when we pull in more components from the shadcn registry, the
 * API stays consistent. Only `default` and `ghost` variants are included
 * here — others can be added as the UI grows.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-strong text-background hover:bg-strong/90",
        ghost: "text-muted hover:bg-surface-2 hover:text-strong",
        outline: "border border-line text-foreground hover:border-line-strong hover:text-strong",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
