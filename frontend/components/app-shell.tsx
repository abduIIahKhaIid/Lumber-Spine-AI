"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import clsx from "clsx";

const NAV = [
  { href: "/single-scan", label: "Single slice" },
  { href: "/multi-scan", label: "Full series" },
  { href: "/assistant", label: "Assistant" },
  { href: "/cases", label: "Cases" },
  { href: "/about", label: "How it works" },
];

export function SpineMark({ className }: { className?: string }) {
  // Three vertebral bodies with disc spaces; the lowest disc carries the accent.
  return (
    <svg viewBox="0 0 28 32" className={className} aria-hidden="true">
      <rect x="5" y="1" width="18" height="7" rx="2.5" fill="currentColor" />
      <rect x="5" y="12" width="18" height="7" rx="2.5" fill="currentColor" />
      <rect x="5" y="23" width="18" height="7" rx="2.5" fill="currentColor" />
      <rect x="7" y="9" width="14" height="2" rx="1" fill="currentColor" opacity=".35" />
      <rect x="7" y="20" width="14" height="2" rx="1" fill="#ef4444" />
    </svg>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const immersive = pathname.startsWith("/assistant");

  return (
    <div className={clsx("flex min-h-dvh flex-col", immersive && "h-dvh")}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-paper focus:p-3"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-50 border-b border-rule bg-bone/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[90rem] items-center gap-6 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5" onClick={() => setOpen(false)}>
            <SpineMark className="h-7 w-6 text-ink" />
            <span className="text-[1.05rem] font-bold tracking-tight">SpineScope</span>
          </Link>
          <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
            {NAV.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "rounded-lg px-3 py-2 text-[0.925rem] font-medium transition-colors",
                    active ? "bg-ink text-white" : "text-graphite hover:bg-paper hover:text-ink",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <span className="ml-auto hidden text-xs text-graphite lg:block">
            Research software, not a medical device
          </span>
          <button
            type="button"
            className="ml-auto rounded-lg border border-rule bg-paper p-2 md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        {open && (
          <nav className="border-t border-rule bg-paper px-4 py-3 md:hidden" aria-label="Main">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="block rounded-lg px-3 py-3 font-medium"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        )}
      </header>
      <main id="main" className={clsx("flex-1", immersive && "min-h-0")}>
        {children}
      </main>
      {!immersive && (
        <footer className="border-t border-rule">
          <div className="mx-auto flex max-w-[90rem] flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-graphite sm:px-6">
            <p>
              SpineScope grades lumbar MRI with research models. Every result needs review by a
              qualified clinician.
            </p>
            <a
              className="underline hover:text-ink"
              href="https://github.com/abduIIahKhaIid/Lumber-Spine-AI"
            >
              Source on GitHub
            </a>
          </div>
        </footer>
      )}
    </div>
  );
}
