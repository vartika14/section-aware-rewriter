/**
 * Every call to the backend goes through this file, so components don't
 * need their own fetch logic, and the base URL only lives in one place.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type Section = {
  id: string;
  heading: string;
  text: string;
};

export type UploadResponse = {
  document_id: string;
  sections: Section[];
  headings_detected: boolean;
};

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    // The backend sends a plain string for most errors, but a list of
    // objects for validation errors. Turn either into one readable sentence.
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((e: { msg?: string }) => e.msg).join("; ")
      : body?.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export type Note = {
  section_id: string;
  heading: string;
  quote: string;
  explanation: string;
  /** False when the quote couldn't be found in that section — a possibly
   *  invented finding, shown but never something the rewrite waited on. */
  verified: boolean;
  /** True when this was a real conflict the model judged serious — most
   *  often one a Hold redraft turned up, which is never asked about a
   *  second time, so this is the only sign it's more than just an FYI. */
  blocking: boolean;
};

export type Option = { key: string; label: string };

export type ConflictItem = {
  section_id: string;
  quote: string;
  explanation: string;
  blocking: boolean;
};

/** One section the rewrite affects, with its quotes and its own three-way
 *  choice. Most rewrites produce exactly one of these; a rewrite touching
 *  more than one commitment produces more. */
export type QuestionGroup = {
  section_id: string;
  heading: string;
  conflicts: ConflictItem[];
  options: Option[];
};

/** `status` says which of the three shapes this is. Only `complete` and
 *  `declined` can come back from answering a question — never a second
 *  question. */
export type RewriteComplete = {
  status: "complete";
  section_id: string;
  old_text: string;
  new_text: string;
  notes: Note[];
};

export type RewriteNeedsClarification = {
  status: "needs_clarification";
  session_id: string;
  section_id: string;
  groups: QuestionGroup[];
};

export type RewriteDeclined = {
  status: "declined";
  section_id: string;
  reason: string;
};

export type RewriteResult =
  | RewriteComplete
  | RewriteNeedsClarification
  | RewriteDeclined;

export async function rewriteSection(input: {
  documentId: string;
  sectionId: string;
  instruction: string;
  currentTexts?: Record<string, string>;
}): Promise<RewriteResult> {
  return unwrap<RewriteResult>(
    await fetch(`${API_BASE}/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: input.documentId,
        section_id: input.sectionId,
        instruction: input.instruction,
        current_texts: input.currentTexts ?? {},
      }),
    }),
  );
}

/**
 * Downloads the finished document as a file (not JSON), so this doesn't use
 * the usual unwrap() helper.
 */
export async function exportDocument(input: {
  documentId: string;
  sections: Record<string, string>;
}): Promise<Blob> {
  const response = await fetch(`${API_BASE}/documents/${input.documentId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sections: Object.entries(input.sections).map(([id, text]) => ({ id, text })),
    }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Export failed (${response.status})`);
  }

  return response.blob();
}

/** Answers a paused question. `choices` is one lettered answer per group's
 *  `section_id`. Can never come back with a second question. */
export async function answerQuestion(input: {
  sessionId: string;
  choices: Record<string, string>;
}): Promise<RewriteComplete | RewriteDeclined> {
  return unwrap<RewriteComplete | RewriteDeclined>(
    await fetch(`${API_BASE}/rewrite/${input.sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choices: input.choices }),
    }),
  );
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  return unwrap<UploadResponse>(
    await fetch(`${API_BASE}/documents`, { method: "POST", body: form }),
  );
}
