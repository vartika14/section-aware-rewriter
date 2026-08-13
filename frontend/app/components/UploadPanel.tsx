"use client";

import { useRef, useState } from "react";
import { uploadDocument, type UploadResponse } from "@/lib/api";

export function UploadPanel({
  onUploaded,
}: {
  onUploaded: (result: UploadResponse, filename: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      onUploaded(await uploadDocument(file), file.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="rounded-lg border border-slate-300 bg-white p-6">
      <h2 className="mb-1 font-semibold">1. Upload a document</h2>
      <p className="mb-4 text-sm text-slate-500">
        A .docx of roughly 2–4 pages with several headed sections.
      </p>

      <input
        ref={input}
        type="file"
        accept=".docx"
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
        }}
        className="block w-full text-sm file:mr-4 file:rounded-md file:border-0
                   file:bg-slate-800 file:px-4 file:py-2 file:text-sm
                   file:font-medium file:text-white hover:file:bg-slate-700
                   disabled:opacity-50"
      />

      {busy && <p className="mt-3 text-sm text-slate-500">Parsing…</p>}
      {error && (
        <p className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}
    </div>
  );
}
