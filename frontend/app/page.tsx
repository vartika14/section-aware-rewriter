"use client";

import { useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { SectionList } from "./components/SectionList";
import { InstructionPanel } from "./components/InstructionPanel";
import { ResultPanel } from "./components/ResultPanel";
import { QuestionPanel } from "./components/QuestionPanel";
import { ExportPanel } from "./components/ExportPanel";
import {
  answerQuestion,
  rewriteSection,
  type RewriteResult,
  type UploadResponse,
} from "@/lib/api";

export default function Home() {
  // document.sections is the single current-state array: it starts as the
  // original upload, and an accepted edit updates the relevant section's
  // text in place (see handleAccept). Anything on screen reads from it
  // directly — there's no separate "current" copy to remember to prefer.
  const [document, setDocument] = useState<UploadResponse | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // A pristine snapshot taken once on upload, never touched again — the
  // only thing this is for is telling editedIds apart from unedited ones.
  const [originalTexts, setOriginalTexts] = useState<Record<string, string>>({});

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RewriteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = document?.sections.find((s) => s.id === selectedId) ?? null;

  async function run(call: () => Promise<RewriteResult>) {
    setBusy(true);
    setError(null);
    try {
      setResult(await call());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rewrite failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleInstruction(instruction: string) {
    if (!document || !selectedId) return;
    setResult(null);
    await run(() =>
      rewriteSection({
        documentId: document.document_id,
        sectionId: selectedId,
        instruction,
        currentTexts: Object.fromEntries(document.sections.map((s) => [s.id, s.text])),
      }),
    );
  }

  async function handleAnswer(sessionId: string, choices: Record<string, string>) {
    await run(() => answerQuestion({ sessionId, choices }));
  }

  // Abandons the pending question — the paused session on the backend is
  // just left unanswered. Clearing the result also unlocks the instruction
  // box and section list, since both lock only while a question is showing.
  function handleCancel() {
    setResult(null);
    setError(null);
  }

  // Only clicking Accept keeps a rewrite. Re-running a rewrite you don't
  // like never overwrites something you already accepted.
  function handleAccept() {
    if (result?.status !== "complete" || !document) return;
    setDocument({
      ...document,
      sections: document.sections.map((s) =>
        s.id === result.section_id ? { ...s, text: result.new_text } : s,
      ),
    });
  }

  const editedIds = new Set(
    (document?.sections ?? [])
      .filter((s) => originalTexts[s.id] !== s.text)
      .map((s) => s.id),
  );

  // While a question is waiting for an answer, block re-typing the
  // instruction or switching sections — either would silently abandon it.
  const awaitingAnswer = result?.status === "needs_clarification";

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
              setOriginalTexts(
                Object.fromEntries(uploaded.sections.map((s) => [s.id, s.text])),
              );
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
                editedIds={editedIds}
                locked={awaitingAnswer}
                onSelect={(id) => {
                  setSelectedId(id);
                  setResult(null);
                  setError(null);
                }}
              />

              <ExportPanel
                documentId={document.document_id}
                filename={filename ?? "document.docx"}
                currentTexts={Object.fromEntries(
                  document.sections.map((s) => [s.id, s.text]),
                )}
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
              locked={awaitingAnswer}
              onSubmit={handleInstruction}
            />
          )}

          {error && (
            <p className="rounded-md bg-red-50 p-4 text-sm text-red-700">{error}</p>
          )}

          {result?.status === "needs_clarification" && (
            <QuestionPanel
              result={result}
              busy={busy}
              onAnswer={(choices) => handleAnswer(result.session_id, choices)}
              onCancel={handleCancel}
            />
          )}

          {/* Declining is a result, not an error: the instruction did not fit
              the section, and saying so beats mangling it confidently. */}
          {result?.status === "declined" && (
            <div className="rounded-lg border border-slate-300 bg-white p-6">
              <h2 className="font-semibold">Not rewritten</h2>
              <p className="mt-2 text-sm text-slate-600">{result.reason}</p>
            </div>
          )}

          {result?.status === "complete" && (
            <ResultPanel
              result={result}
              onAccept={handleAccept}
              accepted={
                document?.sections.find((s) => s.id === result.section_id)?.text ===
                result.new_text
              }
            />
          )}
        </div>
      </div>
    </main>
  );
}
