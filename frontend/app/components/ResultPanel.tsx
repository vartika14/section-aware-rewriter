"use client";

import type { RewriteComplete, Note } from "@/lib/api";

/** Something noticed elsewhere in the document, shown but never applied. */
function NoteCard({ note }: { note: Note }) {
  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-700">{note.heading}</span>
        {!note.verified && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
            unverified
          </span>
        )}
      </div>
      <p className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-600 italic">
        “{note.quote}”
      </p>
      <p className="mt-2 text-sm text-slate-600">{note.explanation}</p>
    </li>
  );
}

export function ResultPanel({
  result,
  onAccept,
  accepted,
}: {
  result: RewriteComplete;
  onAccept: () => void;
  accepted: boolean;
}) {
  return (
    <div className="space-y-6 rounded-lg border border-slate-300 bg-white p-6">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold">4. Result</h2>
          <button
            type="button"
            onClick={onAccept}
            disabled={accepted}
            className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium
                       text-white hover:bg-emerald-800 disabled:bg-slate-300"
          >
            {accepted ? "Accepted" : "Accept into final document"}
          </button>
        </div>
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

      {result.notes.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Also affected — {result.notes.length}, not applied
          </h3>
          <p className="mt-1 mb-3 text-xs text-slate-500">
            Nothing outside the section you picked has been changed.
          </p>
          <ul className="space-y-2">
            {result.notes.map((note, i) => (
              <NoteCard key={`${note.section_id}-${i}`} note={note} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
