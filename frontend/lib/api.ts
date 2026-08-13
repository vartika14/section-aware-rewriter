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

/**
 * `status` is a discriminator. Today "complete" is the only arm; the
 * clarification loop adds "needs_clarification" alongside it, and the UI
 * switches on this field rather than being restructured.
 */
export type RewriteComplete = {
  status: "complete";
  section_id: string;
  old_text: string;
  new_text: string;
};

export type RewriteResult = RewriteComplete;

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

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  return unwrap<UploadResponse>(
    await fetch(`${API_BASE}/documents`, { method: "POST", body: form }),
  );
}
