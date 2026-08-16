/**
 * Every call to the Python API goes through this file, so the components stay
 * free of fetch plumbing and there is one place to change the base URL.
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
    // FastAPI returns a string `detail` for our own HTTPExceptions, but a list
    // of error objects for 422 schema violations. Flatten both to a sentence.
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((e: { msg?: string }) => e.msg).join("; ")
      : body?.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export type Ripple = {
  section_id: string;
  heading: string;
  quote: string;
  kind: string;
  explanation: string;
  proposed_fix: string | null;
  /** False when the quoted clause could not be found where the model said it
   *  was — a possibly invented conflict, shown but never asked about. */
  verified: boolean;
};

export type Option = { key: string; label: string };

/**
 * `status` is the discriminator. All three arms come from both `/rewrite` and
 * `/rewrite/{id}/answer`, so a second question renders exactly like the first.
 */
export type RewriteComplete = {
  status: "complete";
  section_id: string;
  old_text: string;
  new_text: string;
  ripples: Ripple[];
  /** What the agent decided once it had spent its two questions. */
  assumptions: string[];
};

export type RewriteNeedsClarification = {
  status: "needs_clarification";
  session_id: string;
  section_id: string;
  question: string;
  options: Option[];
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
}): Promise<RewriteResult> {
  return unwrap<RewriteResult>(
    await fetch(`${API_BASE}/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: input.documentId,
        section_id: input.sectionId,
        instruction: input.instruction,
      }),
    }),
  );
}

export async function answerQuestion(input: {
  sessionId: string;
  optionKey: string;
}): Promise<RewriteResult> {
  return unwrap<RewriteResult>(
    await fetch(`${API_BASE}/rewrite/${input.sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option_key: input.optionKey }),
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
