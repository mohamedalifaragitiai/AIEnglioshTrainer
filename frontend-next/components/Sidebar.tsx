"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@/app/user-context";
import { Icon } from "@/components/icons";

/**
 * The persistent nav.
 *
 * A rail on desktop, a bottom bar on phones — the same items either way, so the
 * two layouts are one list of links rendered twice rather than two navigations
 * that can drift. Routes and gating are unchanged from the tab bar this
 * replaces: Monitor stays with whoever runs the box, Admin with admins.
 */

type Item = { href: string; label: string; icon: (p: { size?: number }) => React.JSX.Element };

const LEARNER: Item[] = [
  { href: "/", label: "Home", icon: Icon.home },
  { href: "/practice", label: "Practice", icon: Icon.mic },
  { href: "/reading", label: "Reading", icon: Icon.book },
  { href: "/conversations", label: "Conversations", icon: Icon.chat },
  { href: "/report", label: "Reports", icon: Icon.report },
  { href: "/settings", label: "Settings", icon: Icon.settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isAdmin, authRequired } = useUser();
  // "Operator" rather than "admin": with auth off there is one user and nothing
  // to separate, so hiding machine state would only remove a useful view.
  const operator = isAdmin || !authRequired;

  const items = [
    ...LEARNER,
    ...(operator ? [{ href: "/monitor", label: "Monitor", icon: Icon.gauge }] : []),
    ...(isAdmin ? [{ href: "/admin", label: "Admin", icon: Icon.shield }] : []),
  ];

  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  // Nothing to navigate to before signing in — the header hides itself on these
  // pages for the same reason, and a rail of links you cannot open is noise.
  if (pathname === "/login" || pathname === "/signup") return null;

  return (
    <>
      {/* Desktop: a fixed rail. Hidden below lg, where the bottom bar takes over. */}
      <aside className="hidden lg:flex lg:flex-col gap-1 w-[228px] shrink-0 border-r border-line bg-panel min-h-[calc(100dvh-var(--topbar,64px))] sticky top-[var(--topbar,64px)] p-3">
        {items.map(({ href, label, icon: Glyph }) => (
          <Link key={href} href={href} className="nav-item" data-active={active(href)}>
            <span className="icon-badge" style={{ width: 30, height: 30 }}>
              <Glyph size={16} />
            </span>
            {label}
          </Link>
        ))}

        <div className="flex-1" />
        <p className="t-caption px-3 pb-1 leading-relaxed">
          Everything you record stays on this machine.
        </p>
      </aside>

      {/* Phones and tablets: a bottom bar, thumb-reachable. Settings and the
          operator-only views are reachable from the top bar there instead of
          crowding six-plus items into one row. */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-30 border-t border-line bg-panel/95 backdrop-blur flex justify-around px-1 pt-1.5 pb-[max(6px,env(safe-area-inset-bottom))]">
        {LEARNER.slice(0, 5).map(({ href, label, icon: Glyph }) => (
          <Link
            key={href}
            href={href}
            data-active={active(href)}
            className="flex flex-col items-center gap-0.5 px-2 py-1 rounded-lg text-[10px] font-medium text-muted data-[active=true]:text-accent"
          >
            <Glyph size={19} />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
