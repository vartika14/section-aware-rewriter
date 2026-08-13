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
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  return unwrap<UploadResponse>(
    await fetch(`${API_BASE}/documents`, { method: "POST", body: form }),
  );
}
