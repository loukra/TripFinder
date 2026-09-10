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
      <label htmlFor="research-query">What are you trying to find?</label>
      <input
        id="research-query"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="e.g. most underrated US states for nature"
        disabled={disabled}
        required
      />
      <button type="submit" disabled={disabled || query.trim().length === 0}>
        Search
      </button>

      <div className="example-queries">
        <span>Try:</span>
        {EXAMPLE_QUERIES.map((example) => (
          <button
            key={example}
            type="button"
            className="example-query"
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
