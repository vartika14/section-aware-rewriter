"use client";

import type { RewriteComplete, Ripple } from "@/lib/api";

/**
 * A consequence the agent judged not worth interrupting for. Shown, never
 * applied: nothing is written outside the selected section, so the author stays
 * the editor of record.
 */
function RippleCard({ ripple }: { ripple: Ripple }) {
  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-700">{ripple.heading}</span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
          {ripple.kind.replace(/_/g, " ")}
        </span>
        {!ripple.verified && (
          // The quote could not be found where the model said it was, so the
          // conflict may not exist. Shown rather than hidden, but labelled.
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
            unverified
          </span>
        )}
      </div>

      <p className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-600 italic">
        “{ripple.quote}”
      </p>
      <p className="mt-2 text-sm text-slate-600">{ripple.explanation}</p>
      {ripple.proposed_fix && (
        <p className="mt-2 text-sm text-emerald-800">
          <span className="font-medium">Suggested:</span> {ripple.proposed_fix}
        </p>
      )}
    </li>
  );
}

export function ResultPanel({ result }: { result: RewriteComplete }) {
  return (
    <div className="space-y-6 rounded-lg border border-slate-300 bg-white p-6">
      <div>
        <h2 className="mb-4 font-semibold">4. Result</h2>

        <div className="grid gap-4 md:grid-cols-2">
          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Before
            </h3>
            <p className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm text-slate-600">
              {result.old_text || "(empty)"}
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              After
            </h3>
            <p className="whitespace-pre-wrap rounded-md bg-emerald-50 p-3 text-sm text-slate-800">
              {result.new_text}
            </p>
          </section>
        </div>
      </div>

      {/* What the agent decided instead of asking a third time. Stated up front,
          because an assumption the author has to go looking for is a silent one. */}
      {result.assumptions.length > 0 && (
        <section className="rounded-md border border-slate-300 bg-slate-50 p-3">
          <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Assumed, without asking again
          </h3>
          <ul className="mt-2 space-y-1">
            {result.assumptions.map((assumption) => (
              <li key={assumption} className="text-sm text-slate-700">
                {assumption}
              </li>
            ))}
          </ul>
        </section>
      )}

      {result.ripples.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Also affected — {result.ripples.length}, not applied
          </h3>
          <p className="mt-1 mb-3 text-xs text-slate-500">
            Nothing outside the section you picked has been changed.
          </p>
          <ul className="space-y-2">
            {result.ripples.map((ripple, index) => (
              <RippleCard key={`${ripple.section_id}-${index}`} ripple={ripple} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
