"use client";

import { useState } from "react";
import { exportDocument } from "@/lib/api";

/**
 * The download button, with its own loading and error state so a failed
 * download never looks like a failed rewrite.
 *
 * Lives in its own file because it needs the browser's `document` object,
 * and `page.tsx` already has a variable called `document` (the uploaded
 * file) that would shadow it.
 */
export function ExportPanel({
  documentId,
  filename,
  currentTexts,
}: {
  documentId: string;
  filename: string;
  currentTexts: Record<string, string>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload() {
    setBusy(true);
    setError(null);
    try {
      const blob = await exportDocument({ documentId, sections: currentTexts });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${filename.replace(/\.docx$/i, "")}-edited.docx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-300 bg-white p-6">
      <h2 className="mb-1 font-semibold">3. Finish up</h2>
      <p className="mb-4 text-sm text-slate-500">
        Downloads every section as it currently stands — your accepted edits
        where you made them, the original text everywhere else.
      </p>
      <button
        type="button"
        onClick={handleDownload}
        disabled={busy}
        className="w-full rounded-md bg-slate-800 px-4 py-2 text-sm font-medium
                   text-white hover:bg-slate-700 disabled:opacity-40"
      >
        {busy ? "Preparing…" : "Mark complete & download"}
      </button>
      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
    </div>
  );
}
