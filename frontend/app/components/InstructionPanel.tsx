"use client";

import { useState } from "react";
import type { Section } from "@/lib/api";

function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

export function InstructionPanel({
  section,
  busy,
  locked,
  onSubmit,
}: {
  section: Section;
  busy: boolean;
  /** True while a question from an earlier rewrite is still waiting for an
   *  answer. Separate from `busy`: `busy` means "a request is running right
   *  now," `locked` means "you need to answer the question first." Keeping
   *  them apart means the button never wrongly says "Rewriting…" when
   *  nothing is actually running — it's just waiting on you. */
  locked?: boolean;
  onSubmit: (instruction: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const disabled = busy || locked;

  function submit() {
    if (instruction.trim() && !disabled) onSubmit(instruction.trim());
  }

  return (
    <form
      className="rounded-lg border border-slate-300 bg-white p-6"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <h2 className="font-semibold">3. Say how it should change</h2>
      <p className="mb-4 text-sm text-slate-500">
        Rewriting <span className="font-medium">{section.heading}</span> —{" "}
        {wordCount(section.text)} words.
      </p>

      {/* The text being changed stays on screen while the instruction is
          written. Asking someone to describe a change they cannot see is how
          vague instructions happen. */}
      <div className="mb-4 max-h-40 overflow-y-auto rounded-md bg-slate-50 p-3">
        <p className="text-sm whitespace-pre-wrap text-slate-600">
          {section.text || "(no body text)"}
        </p>
      </div>

      <label
        htmlFor="instruction"
        className="mb-2 block text-sm font-medium text-slate-700"
      >
        Your instruction
      </label>
      <textarea
        id="instruction"
        rows={3}
        value={instruction}
        disabled={disabled}
        onChange={(e) => setInstruction(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="Make this concrete. Name the actual deliverables and drop the hedging."
        className="w-full rounded-md border border-slate-300 p-3 text-sm
                   focus:border-slate-500 focus:ring-1 focus:ring-slate-500
                   focus:outline-none disabled:bg-slate-50"
      />

      <div className="mt-3 flex items-center gap-3">
        <button
          type="submit"
          disabled={disabled || !instruction.trim()}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium
                     text-white hover:bg-slate-700 disabled:opacity-40"
        >
          {busy ? "Rewriting…" : "Rewrite section"}
        </button>
        {locked ? (
          <span className="text-xs text-amber-700">Answer the question first.</span>
        ) : (
          <span className="text-xs text-slate-400">⌘↵ to submit</span>
        )}
      </div>
    </form>
  );
}
