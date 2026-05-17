"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  askVideo,
  fmtTime,
  frameSrc,
  getFrames,
  getTimeline,
  semanticSearch,
  type ChunkEntry,
  type FrameRef,
} from "@/lib/api";

export default function VideoPage() {
  const params = useParams<{ id: string }>();
  const videoId = params.id;

  const [timeline, setTimeline] = useState<ChunkEntry[]>([]);
  const [frames, setFrames] = useState<FrameRef[]>([]);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [results, setResults] = useState<ChunkEntry[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!videoId) return;
    getTimeline(videoId).then(setTimeline).catch(console.error);
    getFrames(videoId).then(setFrames).catch(console.error);
  }, [videoId]);

  async function onAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!query) return;
    setBusy(true);
    setAnswer(null);
    try {
      const [askResp, searchResp] = await Promise.all([
        askVideo(videoId, query),
        semanticSearch(videoId, query),
      ]);
      setAnswer(askResp.answer || null);
      setResults(searchResp);
      const fr = await getFrames(videoId, query, 6);
      setFrames(fr);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="space-y-8">
      <header>
        <h2 className="text-lg font-medium">Video</h2>
        <code className="text-xs text-slate-400">{videoId}</code>
      </header>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <form onSubmit={onAsk} className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about this video..."
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !query}
            className="rounded bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-50"
          >
            {busy ? "..." : "Ask"}
          </button>
        </form>
        {answer && (
          <div className="mt-4 whitespace-pre-wrap rounded border border-slate-800 bg-slate-950 p-3 text-sm">
            {answer}
          </div>
        )}
        {results.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm">
            {results.map((r) => (
              <li key={r.chunk_id} className="text-slate-300">
                <span className="text-slate-500">[{fmtTime(r.start)}–{fmtTime(r.end)}]</span>{" "}
                {r.summary}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-medium text-slate-400">Timeline</h3>
        <ol className="space-y-2">
          {timeline.map((c) => (
            <li key={c.chunk_id} className="rounded border border-slate-800 p-3 text-sm">
              <div className="text-slate-500">[{fmtTime(c.start)}–{fmtTime(c.end)}]</div>
              <div>{c.summary}</div>
              {c.entities?.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {c.entities.slice(0, 6).map((e) => (
                    <span key={e} className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
                      {e}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-medium text-slate-400">Frames</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {frames.map((f) => (
            <figure key={f.frame_path} className="overflow-hidden rounded border border-slate-800">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={frameSrc(videoId, f.frame_path)} alt={f.why} className="aspect-video w-full object-cover" />
              <figcaption className="bg-slate-950 px-2 py-1 text-xs text-slate-400">
                t={fmtTime(f.timestamp)} · {f.why}
              </figcaption>
            </figure>
          ))}
        </div>
      </section>
    </main>
  );
}
