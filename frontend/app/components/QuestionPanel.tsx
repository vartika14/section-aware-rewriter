"use client";

import type { RewriteNeedsClarification } from "@/lib/api";

/**
 * The interrupt. It exists because the rewrite would otherwise break a promise
 * made elsewhere in the document, and only the author can say which way that
 * should go — so the clause is quoted in full rather than summarised, and the
 * branches are buttons rather than a text box.
 */
export function QuestionPanel({
  result,
  busy,
  onAnswer,
  onCancel,
}: {
  result: RewriteNeedsClarification;
  busy: boolean;
  onAnswer: (optionKey: string) => void;
  /** Steps back from the question entirely — none of the three answers fit,
   *  the author wants to change what they asked for instead. Nothing is
   *  undone on the server, because nothing was ever applied; the paused
   *  question is simply left unanswered, the same as if the author had
   *  never come back to it. */
  onCancel: () => void;
}) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-6">
      <h2 className="font-semibold text-amber-900">One thing before I write it</h2>

      <p className="mt-3 mb-5 text-sm leading-relaxed whitespace-pre-wrap text-slate-800">
        {result.question}
      </p>

      <div className="space-y-2">
        {result.options.map((option) => (
          <button
            key={option.key}
            type="button"
            disabled={busy}
            onClick={() => onAnswer(option.key)}
            className="flex w-full items-start gap-3 rounded-md border
                       border-amber-300 bg-white p-3 text-left text-sm
                       hover:border-amber-500 hover:bg-amber-100
                       disabled:opacity-50"
          >
            <span className="font-semibold text-amber-800 uppercase">
              {option.key}
            </span>
            <span className="text-slate-700">{option.label}</span>
          </button>
        ))}
      </div>

      {/* Deliberately styled apart from the three answers above — this isn't
          a fourth way to resolve the conflict, it's stepping back from the
          question to change the instruction instead. */}
      <button
        type="button"
        disabled={busy}
        onClick={onCancel}
        className="mt-3 w-full rounded-md border border-dashed border-slate-300
                   bg-transparent px-3 py-2 text-sm text-slate-500
                   hover:border-slate-400 hover:bg-slate-50 hover:text-slate-700
                   disabled:opacity-50"
      >
        Cancel — let me change my instruction instead
      </button>

      {busy && <p className="mt-4 text-xs text-amber-800">Applying your answer…</p>}
    </div>
  );
}
