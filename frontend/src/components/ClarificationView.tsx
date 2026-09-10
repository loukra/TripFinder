"use client";

import { useState } from "react";
import type { ClarificationRequest, EntityType } from "@/lib/types";

interface ClarificationViewProps {
  clarification: ClarificationRequest;
  onAnswer: (entityGranularity: EntityType) => void;
  submitting: boolean;
}

// `allow_grouped` ("show all tiers, grouped") is deliberately not offered
// here: the backend's ClarifyRequest only accepts one entity_granularity
// (see api/schemas.py's ClarifyRequest docstring), so offering it would be
// a UI promise this phase's API cannot keep.
export function ClarificationView({ clarification, onAnswer, submitting }: ClarificationViewProps) {
  const [selected, setSelected] = useState<EntityType | null>(null);

  return (
    <section className="clarification" aria-label="Clarification needed">
      <h2>{clarification.question}</h2>
      <fieldset disabled={submitting}>
        {clarification.options.map((option) => (
          <label key={option.entity_granularity} className="clarification-option">
            <input
              type="radio"
              name="clarification-option"
              value={option.entity_granularity}
              checked={selected === option.entity_granularity}
              onChange={() => setSelected(option.entity_granularity)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      <button
        type="button"
        disabled={selected === null || submitting}
        onClick={() => selected !== null && onAnswer(selected)}
      >
        Continue
      </button>
    </section>
  );
}
