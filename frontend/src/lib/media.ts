import { api } from "@/services/api";

const cache = new Map<string, { token: string; exp: number }>();

/** Short-lived, document-scoped token so <img>/<video> can load authorised media. Cached until near expiry. */
export async function mediaToken(docId: string): Promise<string> {
  const hit = cache.get(docId);
  if (hit && hit.exp > Date.now() + 30_000) return hit.token;
  const r = await api.mediaToken(docId);
  cache.set(docId, { token: r.token, exp: Date.now() + r.expires_in * 1000 });
  return r.token;
}

export const mediaUrl = (docId: string, token: string) => `/api/media/documents/${docId}?t=${encodeURIComponent(token)}`;
export const pageImageUrl = (docId: string, page: number, token: string) => `/api/media/documents/${docId}/pages/${page}.png?t=${encodeURIComponent(token)}`;
export const figureImageUrl = (docId: string, figureRef: string, token: string) => `/api/media/documents/${docId}/figures/${encodeURIComponent(figureRef)}?t=${encodeURIComponent(token)}`;
