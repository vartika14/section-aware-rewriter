"use client";

import { useState } from "react";
import type { QuestionGroup, RewriteNeedsClarification } from "@/lib/api";

/** One row: one section the rewrite affects, and its three possible answers.
 *  Clicking an answer just selects it — nothing is sent until every row has
 *  a selection and Continue is clicked. */
function ConflictRow({
  group,
  selected,
  onSelect,
}: {
  group: QuestionGroup;
  selected: string | null;
  onSelect: (optionKey: string) => void;
}) {
  return (
    <div className="rounded-md border border-amber-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-amber-900">{group.heading}</h3>

      <ul className="mt-2 space-y-1.5">
        {group.conflicts.map((c, i) => (
          <li key={i} className="text-sm leading-relaxed text-slate-700">
            <span className="text-slate-500">“{c.quote}”</span> — {c.explanation}
          </li>
        ))}
      </ul>

      <div className="mt-3 space-y-1.5">
        {group.options.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => onSelect(option.key)}
            aria-pressed={selected === option.key}
            className={`flex w-full items-start gap-3 rounded-md border p-2.5 text-left text-sm
                        ${
                          selected === option.key
                            ? "border-amber-500 bg-amber-100"
                            : "border-amber-200 bg-white hover:border-amber-400 hover:bg-amber-50"
                        }`}
          >
            <span className="font-semibold text-amber-800 uppercase">
              {option.key}
            </span>
            <span className="text-slate-700">{option.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function QuestionPanel({
  result,
  busy,
  onAnswer,
  onCancel,
}: {
  result: RewriteNeedsClarification;
  busy: boolean;
  /** One lettered choice per group, sent together once every row is answered. */
  onAnswer: (choices: Record<string, string>) => void;
  /** Abandons the question so the author can change the instruction
   *  instead. Nothing to undo — nothing was applied yet. */
  onCancel: () => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const allAnswered = result.groups.every((g) => choices[g.section_id]);

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-6">
      <h2 className="font-semibold text-amber-900">
        {result.groups.length === 1
          ? "One thing before I write it"
          : `${result.groups.length} things before I write it`}
      </h2>
      <p className="mt-1 mb-4 text-sm text-amber-800">
        This rewrite affects the section{result.groups.length === 1 ? "" : "s"} below.
        Answer each one, then continue.
      </p>

      <div className="space-y-3">
        {result.groups.map((group) => (
          <ConflictRow
            key={group.section_id}
            group={group}
            selected={choices[group.section_id] ?? null}
            onSelect={(key) =>
              setChoices((prev) => ({ ...prev, [group.section_id]: key }))
            }
          />
        ))}
      </div>

      <button
        type="button"
        disabled={busy || !allAnswered}
        onClick={() => onAnswer(choices)}
        className="mt-4 w-full rounded-md bg-amber-700 px-4 py-2 text-sm font-medium
                   text-white hover:bg-amber-800 disabled:opacity-40"
      >
        {busy ? "Applying your answers…" : "Continue"}
      </button>

      {/* Styled apart from the rows above — this isn't another answer, it's
          backing out of the question entirely. */}
      <button
        type="button"
        disabled={busy}
        onClick={onCancel}
        className="mt-2 w-full rounded-md border border-dashed border-slate-300
                   bg-transparent px-3 py-2 text-sm text-slate-500
                   hover:border-slate-400 hover:bg-slate-50 hover:text-slate-700
                   disabled:opacity-50"
      >
        Cancel — let me change my instruction instead
      </button>
    </div>
  );
}
