import type { Metadata } from "next";
import Link from "next/link";
import { Caprasimo, Figtree } from "next/font/google";
import "./globals.css";

// The design system's two faces (ds/styles.css). Caprasimo ships a single
// weight; Figtree carries the body and the weights the UI actually uses.
const caprasimo = Caprasimo({
  variable: "--font-caprasimo",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

const figtree = Figtree({
  variable: "--font-figtree",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "TripFinder",
  description: "Opinion-based travel research engine",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${caprasimo.variable} ${figtree.variable}`}>
      <body>
        {/* The header is the site's, not the landing page's: since 14.9 a
            run has its own URL and a history page lists past ones, so every
            page needs the way back and the way to the list. */}
        <header className="site-header">
          <Link className="brand" href="/">
            <span className="brand-mark" aria-hidden="true" />
            <span className="brand-name">TripFinder</span>
          </Link>
          <nav className="site-nav" aria-label="Main">
            <Link className="btn btn-ghost" href="/history">
              History
            </Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
