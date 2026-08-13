"use client";

import { useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { SectionList } from "./components/SectionList";
import type { UploadResponse } from "@/lib/api";

export default function Home() {
  const [document, setDocument] = useState<UploadResponse | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected =
    document?.sections.find((s) => s.id === selectedId) ?? null;

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold">Section-aware rewrite agent</h1>
        <p className="text-slate-500">
          Rewrite one section without breaking the rest of the document.
        </p>
      </header>

      <UploadPanel
        onUploaded={(result, name) => {
          setDocument(result);
          setFilename(name);
          setSelectedId(null);
        }}
      />

      {document && (
        <>
          <p className="text-sm text-slate-500">
            Loaded <span className="font-medium text-slate-700">{filename}</span>
          </p>

          <SectionList
            sections={document.sections}
            headingsDetected={document.headings_detected}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </>
      )}

      {selected && (
        <div className="rounded-lg border border-slate-300 bg-white p-6">
          <h2 className="mb-3 font-semibold">{selected.heading}</h2>
          <p className="whitespace-pre-wrap text-sm text-slate-700">
            {selected.text || "(no body text)"}
          </p>
        </div>
      )}
    </main>
  );
}
