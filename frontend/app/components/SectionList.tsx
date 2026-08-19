"use client";

import type { Section } from "@/lib/api";

export function SectionList({
  sections,
  headingsDetected,
  selectedId,
  editedIds,
  locked,
  onSelect,
}: {
  sections: Section[];
  headingsDetected: boolean;
  selectedId: string | null;
  editedIds: Set<string>;
  /** True while a question is waiting for an answer — picking a different
   *  section is turned off so the question can't be silently abandoned. */
  locked?: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-300 bg-white p-6">
      <h2 className="mb-1 font-semibold">2. Pick a section</h2>
      <p className="mb-4 text-sm text-slate-500">
        {sections.length} section{sections.length === 1 ? "" : "s"} found.
        {editedIds.size > 0 &&
          ` ${editedIds.size} edited.`}
      </p>

      {locked && (
        <p className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
          Answer the question on the right before picking a different section.
        </p>
      )}

      {!headingsDetected && (
        <p className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
          No heading styles found in this document, so these boundaries are a
          guess based on blank lines. Check them before relying on a rewrite.
        </p>
      )}

      <ul className="space-y-2">
        {sections.map((section) => (
          <li key={section.id}>
            <label
              className={`flex gap-3 rounded-md border p-3 ${
                locked ? "cursor-not-allowed opacity-60" : "cursor-pointer"
              } ${
                selectedId === section.id
                  ? "border-slate-800 bg-slate-50"
                  : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <input
                type="radio"
                name="section"
                className="mt-1"
                checked={selectedId === section.id}
                disabled={locked}
                onChange={() => onSelect(section.id)}
              />
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 font-medium">
                  {section.heading}
                  {editedIds.has(section.id) && (
                    <span className="text-emerald-600" title="Edited and accepted">
                      ●
                    </span>
                  )}
                </span>
                <span className="block truncate text-sm text-slate-500">
                  {section.text || "(no body text)"}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
