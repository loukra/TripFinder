import type { Metadata } from "next";
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
      <body>{children}</body>
    </html>
  );
}
