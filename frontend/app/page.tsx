"use client";

import { useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { SectionList } from "./components/SectionList";
import { InstructionPanel } from "./components/InstructionPanel";
import { ResultPanel } from "./components/ResultPanel";
import { rewriteSection, type RewriteResult, type UploadResponse } from "@/lib/api";

export default function Home() {
  const [document, setDocument] = useState<UploadResponse | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RewriteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = document?.sections.find((s) => s.id === selectedId) ?? null;

  async function handleInstruction(instruction: string) {
    if (!document || !selectedId) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await rewriteSection({
          documentId: document.document_id,
          sectionId: selectedId,
          instruction,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rewrite failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold">Section-aware rewrite agent</h1>
        <p className="text-slate-500">
          Rewrite one section without breaking the rest of the document.
        </p>
      </header>

      {/* Two columns once a document is loaded: the section list stays pinned
          on the left, so it is always clear which section a result belongs to
          without scrolling back up. */}
      <div className="grid gap-6 md:grid-cols-[20rem_1fr] md:items-start">
        <div className="space-y-4">
          <UploadPanel
            onUploaded={(uploaded, name) => {
              setDocument(uploaded);
              setFilename(name);
              setSelectedId(null);
              setResult(null);
              setError(null);
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
                onSelect={(id) => {
                  setSelectedId(id);
                  setResult(null);
                  setError(null);
                }}
              />
            </>
          )}
        </div>

        <div className="space-y-6">
          {document && !selected && (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">
              Pick a section on the left to rewrite it.
            </p>
          )}

          {selected && (
            <InstructionPanel
              section={selected}
              busy={busy}
              onSubmit={handleInstruction}
            />
          )}

          {error && (
            <p className="rounded-md bg-red-50 p-4 text-sm text-red-700">{error}</p>
          )}

          {result?.status === "complete" && <ResultPanel result={result} />}
        </div>
      </div>
    </main>
  );
}
