"use client";

import { useState } from "react";
import type { Section } from "@/lib/api";

export function InstructionPanel({
  section,
  busy,
  onSubmit,
}: {
  section: Section;
  busy: boolean;
  onSubmit: (instruction: string) => void;
}) {
  const [instruction, setInstruction] = useState("");

  return (
    <form
      className="rounded-lg border border-slate-300 bg-white p-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (instruction.trim()) onSubmit(instruction.trim());
      }}
    >
      <h2 className="mb-1 font-semibold">3. Say how it should change</h2>
      <p className="mb-4 text-sm text-slate-500">
        Rewriting <span className="font-medium">{section.heading}</span>, in plain
        language.
      </p>

      <textarea
        rows={3}
        value={instruction}
        disabled={busy}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder="Make this concrete. Name the actual deliverables and drop the hedging."
        className="w-full rounded-md border border-slate-300 p-3 text-sm
                   disabled:bg-slate-50"
      />

      <button
        type="submit"
        disabled={busy || !instruction.trim()}
        className="mt-3 rounded-md bg-slate-800 px-4 py-2 text-sm font-medium
                   text-white hover:bg-slate-700 disabled:opacity-40"
      >
        {busy ? "Rewriting…" : "Rewrite section"}
      </button>
    </form>
  );
}
