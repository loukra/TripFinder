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
    <section className="section clarification rise" aria-label="Clarification needed">
      <div className="panel">
        <h2 className="clarification-title">{clarification.question}</h2>
        {/* Deliberately avoids the word "grouped": the guard test above keeps
            any hint of the unsupported `allow_grouped` answer out of this view. */}
        <p className="text-muted clarification-hint">
          This decides how specific the answers will be.
        </p>

        <fieldset disabled={submitting} className="clarification-options">
          {clarification.options.map((option) => (
            <label key={option.entity_granularity} className="radio">
              <input
                type="radio"
                name="clarification-option"
                value={option.entity_granularity}
                checked={selected === option.entity_granularity}
                onChange={() => setSelected(option.entity_granularity)}
              />
              <span className="dot" />
              <span>{option.label}</span>
            </label>
          ))}
        </fieldset>

        <div className="clarification-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={selected === null || submitting}
            onClick={() => selected !== null && onAnswer(selected)}
          >
            Continue
          </button>
        </div>
      </div>
    </section>
  );
}
