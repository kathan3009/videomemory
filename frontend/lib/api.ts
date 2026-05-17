export const API = "/api"; // proxied to FastAPI by next.config.mjs

export type Video = {
  video_id: string;
  title: string | null;
  duration: number;
  status: string;
  ingested_at: string;
};

export async function listVideos(): Promise<Video[]> {
  const r = await fetch(`${API}/videos`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listVideos ${r.status}`);
  const j = await r.json();
  return j.videos;
}

export async function ingestUrl(source: string): Promise<{ job_id: string }> {
  const r = await fetch(`${API}/videos/ingest_url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source }),
  });
  if (!r.ok) throw new Error(`ingestUrl ${r.status}`);
  return r.json();
}

export async function uploadVideo(file: File): Promise<{ job_id: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API}/videos/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(`upload ${r.status}`);
  return r.json();
}

export type ChunkEntry = {
  chunk_id: string;
  start: number;
  end: number;
  summary: string;
  entities: string[];
  scene_ids: string[];
};

export async function getTimeline(videoId: string): Promise<ChunkEntry[]> {
  const r = await fetch(`${API}/videos/${videoId}/timeline?granularity=chunk`, { cache: "no-store" });
  if (!r.ok) throw new Error(`timeline ${r.status}`);
  const j = await r.json();
  return j.entries;
}

export type FrameRef = {
  frame_path: string;
  timestamp: number;
  scene_id: string;
  why: string;
  score: number;
};

export async function getFrames(videoId: string, query?: string, limit = 8): Promise<FrameRef[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (query) q.set("query", query);
  const r = await fetch(`${API}/videos/${videoId}/frames?${q}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`frames ${r.status}`);
  const j = await r.json();
  return j.frames;
}

export async function semanticSearch(videoId: string, query: string) {
  const r = await fetch(`${API}/videos/${videoId}/semantic_search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!r.ok) throw new Error(`search ${r.status}`);
  return (await r.json()).results;
}

export async function askVideo(videoId: string, query: string) {
  const r = await fetch(`${API}/videos/${videoId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!r.ok) throw new Error(`ask ${r.status}`);
  return r.json();
}

export function frameSrc(videoId: string, framePath: string): string {
  const name = framePath.split("/").pop() || framePath;
  return `${API}/videos/${videoId}/frames/${name}`;
}

export function fmtTime(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
