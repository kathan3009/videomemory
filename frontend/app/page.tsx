"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ingestUrl, listVideos, uploadVideo, type Video } from "@/lib/api";

export default function HomePage() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");

  async function refresh() {
    try {
      setVideos(await listVideos());
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, []);

  async function onUrlSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url) return;
    setBusy(true);
    setError(null);
    try {
      await ingestUrl(url);
      setUrl("");
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    setError(null);
    try {
      await uploadVideo(f);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="space-y-8">
      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-6">
        <h2 className="mb-3 text-lg font-medium">Ingest a video</h2>
        <form onSubmit={onUrlSubmit} className="flex gap-2">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://youtu.be/..."
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !url}
            className="rounded bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-50"
          >
            Ingest URL
          </button>
        </form>
        <div className="mt-4 text-sm text-slate-400">— or —</div>
        <label className="mt-2 inline-flex cursor-pointer items-center gap-2 rounded border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800">
          <input type="file" accept="video/*" onChange={onFile} className="hidden" />
          Upload a video file
        </label>
        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-medium">Videos</h2>
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">video_id</th>
                <th className="px-3 py-2 text-left">title</th>
                <th className="px-3 py-2 text-right">duration</th>
                <th className="px-3 py-2 text-left">status</th>
              </tr>
            </thead>
            <tbody>
              {videos.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-slate-500">
                    No videos yet — paste a URL or upload one above.
                  </td>
                </tr>
              )}
              {videos.map((v) => (
                <tr key={v.video_id} className="border-t border-slate-800 hover:bg-slate-900/40">
                  <td className="px-3 py-2 font-mono text-xs">
                    <Link href={`/videos/${v.video_id}`} className="text-emerald-300 hover:underline">
                      {v.video_id}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{v.title || "(untitled)"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{Math.round(v.duration)}s</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${v.status === "completed" ? "bg-emerald-900 text-emerald-200" : "bg-amber-900 text-amber-200"}`}>
                      {v.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
