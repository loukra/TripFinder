"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, createResearch } from "@/lib/api";
import { SearchForm } from "@/components/SearchForm";

const HOW_IT_WORKS = [
  {
    title: "Real discussions",
    body: "The agent searches communities for threads where people answer this kind of question.",
  },
  {
    title: "One person, one vote",
    body: "Repeat commenters are de-duplicated, so enthusiasm cannot inflate a place.",
  },
  {
    title: "Evidence attached",
    body: "Every ranking links back to the comments it was counted from.",
  },
];

/**
 * The landing page: ask a question, and go to the run that answers it.
 *
 * Since 14.9 (plan §2.15) the run itself lives at its own URL rather than
 * in this page's state. A research outliving the tab that started it is the
 * whole point — one that can only be watched, never reopened, has to be
 * bought again to be read again.
 */
export default function Home() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSearch(query: string) {
    setError(null);
    setSubmitting(true);
    try {
      const created = await createResearch(query);
      router.push(`/research/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "could not start this research");
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <section className="hero">
        <p className="hero-kicker">Opinion research</p>
        <h1 className="hero-title">Ask the people who actually went.</h1>
        <p className="text-muted hero-lede">
          TripFinder reads real discussions, counts independent opinions and ranks what comes out.
          Nothing here is invented.
        </p>

        <SearchForm onSubmit={handleSearch} disabled={submitting} />

        {error && <p className="error">{error}</p>}

        <ul className="how-it-works">
          {HOW_IT_WORKS.map((item) => (
            <li key={item.title} className="how-card">
              <span className="how-card-title">{item.title}</span>
              <span className="text-muted how-card-body">{item.body}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
