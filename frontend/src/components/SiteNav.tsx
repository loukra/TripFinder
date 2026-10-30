"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// The site's way back to the search and on to the list. "New research" sits
// here rather than beside a run's question, where it pushed the question into
// a narrow column with an empty stretch beside it; on the search page itself
// it would link to where the user already is.
export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav className="site-nav" aria-label="Main">
      <Link className="btn btn-ghost" href="/history">
        History
      </Link>
      {pathname !== "/" && (
        <Link className="btn btn-secondary" href="/">
          New research
        </Link>
      )}
    </nav>
  );
}
