"use client";

import { useState } from "react";
import type { FormEvent } from "react";

const EXAMPLE_QUERIES = [
  "most underrated US states for nature",
  "best national parks avoiding crowds",
  "underrated European road-trip regions",
];

interface SearchFormProps {
  onSubmit: (query: string) => void;
  disabled: boolean;
}

export function SearchForm({ onSubmit, disabled }: SearchFormProps) {
  const [query, setQuery] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length === 0) return;
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="search-form">
      <div className="search-row">
        {/* The hero heading carries the visible prompt, so the field takes its
            accessible name from aria-label rather than a second visible label. */}
        <input
          id="research-query"
          className="input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="most underrated US states for nature"
          aria-label="What are you trying to find?"
          disabled={disabled}
          required
        />
        <button type="submit" className="btn btn-primary" disabled={disabled || query.trim().length === 0}>
          Search
        </button>
      </div>

      <div className="example-queries">
        <span className="text-muted example-queries-label">Try</span>
        {EXAMPLE_QUERIES.map((example) => (
          <button
            key={example}
            type="button"
            className="tag tag-outline example-query"
            disabled={disabled}
            onClick={() => setQuery(example)}
          >
            {example}
          </button>
        ))}
      </div>
    </form>
  );
}
