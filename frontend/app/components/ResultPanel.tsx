"use client";

import type { RewriteComplete } from "@/lib/api";

export function ResultPanel({ result }: { result: RewriteComplete }) {
  return (
    <div className="rounded-lg border border-slate-300 bg-white p-6">
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
  );
}
