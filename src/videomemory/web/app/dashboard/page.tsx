'use client';

import { CSSProperties, FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowUpRight,
  Check,
  Copy,
  CreditCard,
  FileVideo,
  KeyRound,
  LayoutDashboard,
  Library,
  Link2,
  LogOut,
  Network,
  PackageOpen,
  PlugZap,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
  type LucideIcon,
} from 'lucide-react';
import { Brand, Mark } from '../components/Mark';
import { API_URL, api } from '../lib/api';

type User = { user_id: string; name: string; email: string; plan: 'free' | 'creator' | 'studio'; created_at: string };
type Usage = { plan: string; limits: Record<string, number>; totals: Record<string, number>; period_start: string };
type Video = { video_id: string; source: string; title?: string; duration: number; added_at: string };
type Job = { job_id: string; source: string; status: string; progress: number; error?: string; created_at: string };
type TranscriptWindow = { window_id: string; start: number; end: number; text: string };
type VideoHit = { start: number; end: number; timestamp_human: string; transcript_excerpt: string; score: number; deep_link?: string };
type VideoDetail = { video: Video; transcript: TranscriptWindow[] };
type ApiKey = { name: string; prefix: string; created_at: string; last_used_at?: string };
type MemoryNode = { node_id: string; node_type: 'video' | 'query' | 'moment' | 'note' | 'artifact' | 'project'; label: string; access_count: number; properties: Record<string, unknown>; updated_at: string };
type MemoryEdge = { edge_id: string; source_id: string; target_id: string; relation: string; weight: number; updated_at: string };
type MemoryNote = { note_id: string; video_id: string; parent_note_id?: string; title: string; body: string; version: number; created_at: string };
type MemoryGraph = { nodes: MemoryNode[]; edges: MemoryEdge[]; events: { event_id: string; tool: string; query?: string; video_id?: string; created_at: string }[]; notes: MemoryNote[] };
type Artifact = { artifact_id: string; kind: string; title: string; locator: string; access_instructions: string; summary: string; project: string; agent: string; version: number; updated_at: string };
type Account = {
  user: User;
  usage: Usage;
  api_keys: ApiKey[];
  videos: Video[];
  jobs: Job[];
  billing: { enabled: boolean; key_id: string; plans: Record<string, { name: string; amount: number; currency: string }>; subscription?: { status: string; current_period_end?: string } };
};
type Checkout = { subscription_id: string; plan: string; amount: number; currency: string; key_id: string; customer: { name: string; email: string } };

declare global {
  interface Window {
    Razorpay: new (options: Record<string, unknown>) => { open: () => void };
  }
}

const MCP_URL = process.env.NEXT_PUBLIC_MCP_URL || `${API_URL}/mcp`;

const NAV_ITEMS: { id: 'overview' | 'library' | 'memory' | 'artifacts' | 'connections' | 'billing'; label: string; icon: LucideIcon }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'library', label: 'Library', icon: Library },
  { id: 'memory', label: 'Memory', icon: Network },
  { id: 'artifacts', label: 'Artifacts', icon: PackageOpen },
  { id: 'connections', label: 'Connections', icon: PlugZap },
  { id: 'billing', label: 'Billing', icon: CreditCard },
];

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${remainder.toString().padStart(2, '0')}`;
}

function relativeTime(value?: string) {
  if (!value) return 'Never';
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function sourceLabel(source: string) {
  try {
    const parsed = new URL(source);
    return parsed.protocol === 'upload:' ? 'Uploaded file' : parsed.hostname;
  } catch {
    return 'Uploaded file';
  }
}

async function loadRazorpay() {
  if (window.Razorpay) return;
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Payment window could not load'));
    document.head.appendChild(script);
  });
}

export default function DashboardPage() {
  const router = useRouter();
  const [account, setAccount] = useState<Account | null>(null);
  const [section, setSection] = useState<'overview' | 'library' | 'memory' | 'artifacts' | 'connections' | 'billing'>('overview');
  const [videoUrl, setVideoUrl] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadInputKey, setUploadInputKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [newKey, setNewKey] = useState('');
  const [keyName, setKeyName] = useState('Production agent');
  const [memory, setMemory] = useState<MemoryGraph | null>(null);
  const [noteVideo, setNoteVideo] = useState('');
  const [noteParent, setNoteParent] = useState('');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteBody, setNoteBody] = useState('');
  const [selectedVideo, setSelectedVideo] = useState<VideoDetail | null>(null);
  const [videoQuestion, setVideoQuestion] = useState('');
  const [videoHits, setVideoHits] = useState<VideoHit[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'checking' | 'healthy' | 'failed'>('idle');
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactTitle, setArtifactTitle] = useState('');
  const [artifactLocator, setArtifactLocator] = useState('');
  const [artifactSummary, setArtifactSummary] = useState('');
  const [artifactProject, setArtifactProject] = useState('');
  const [artifactKind, setArtifactKind] = useState('code');

  const refresh = useCallback(async () => {
    try {
      const next = await api<Account>('/api/account');
      setAccount(next);
      setError('');
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Could not load your account';
      if (message.includes('sign in')) router.replace('/login');
      else setError(message);
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const timer = window.setTimeout(refresh, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const requested = new URLSearchParams(window.location.search).get('section');
      if (NAV_ITEMS.some((item) => item.id === requested)) setSection(requested as typeof section);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (!account?.jobs.some((job) => ['queued', 'processing'].includes(job.status))) return;
    const timer = window.setInterval(refresh, 4000);
    return () => window.clearInterval(timer);
  }, [account?.jobs, refresh]);

  const loadMemory = useCallback(async () => {
    try { setMemory(await api<MemoryGraph>('/api/memory?limit=80')); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not load memory graph'); }
  }, []);

  useEffect(() => {
    if (section !== 'memory') return;
    const timer = window.setTimeout(loadMemory, 0);
    return () => window.clearTimeout(timer);
  }, [section, loadMemory]);
  useEffect(() => {
    if (section !== 'artifacts') return;
    api<{ artifacts: Artifact[] }>('/api/artifacts').then((result) => setArtifacts(result.artifacts)).catch((caught) => setError(caught instanceof Error ? caught.message : 'Could not load artifacts'));
  }, [section]);

  const stats = useMemo(() => {
    if (!account) return [];
    const totals = account.usage.totals;
    return [
      ['VIDEOS', Math.round(totals.videos || 0), account.usage.limits.videos],
      ['MINUTES', Math.round(totals.minutes || 0), account.usage.limits.minutes],
      ['MCP CALLS', Math.round(totals.mcp_calls || 0), account.usage.limits.mcp_calls],
    ] as const;
  }, [account]);

  async function addVideo(event: FormEvent) {
    event.preventDefault();
    setWorking(true); setError(''); setNotice('');
    try {
      await api('/api/videos', { method: 'POST', body: JSON.stringify({ url: videoUrl }) });
      setVideoUrl('');
      setNotice('Video queued. The library will update when indexing finishes.');
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add this video');
    } finally { setWorking(false); }
  }

  async function uploadVideo(event: FormEvent) {
    event.preventDefault();
    if (!uploadFile) return;
    setWorking(true); setError(''); setNotice('');
    try {
      await api('/api/uploads', {
        method: 'POST',
        body: uploadFile,
        headers: {
          'Content-Type': uploadFile.type || 'application/octet-stream',
          'X-Videomemory-Filename': uploadFile.name,
        },
      });
      setNotice(`${uploadFile.name} is securely uploaded and queued for indexing.`);
      setUploadFile(null);
      setUploadInputKey((value) => value + 1);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not upload this video');
    } finally { setWorking(false); }
  }

  async function createKey(event: FormEvent) {
    event.preventDefault();
    setWorking(true); setError('');
    try {
      const response = await api<{ api_key: string }>('/api/keys', { method: 'POST', body: JSON.stringify({ name: keyName }) });
      setNewKey(response.api_key);
      await refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not create key'); }
    finally { setWorking(false); }
  }

  async function revokeKey(prefix: string) {
    if (!window.confirm(`Revoke ${prefix}…? Connected agents using it will stop working.`)) return;
    try { await api(`/api/keys/${encodeURIComponent(prefix)}`, { method: 'DELETE' }); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not revoke this key'); }
  }

  async function logout() {
    try { await api('/api/auth/logout', { method: 'POST', body: '{}' }); }
    catch { /* Local sign-out still removes the browser credential. */ }
    finally { window.localStorage.removeItem('vm_session'); router.push('/'); }
  }

  async function copyKey() {
    await navigator.clipboard.writeText(newKey);
    setNotice('MCP key copied. Store it in your agent environment now.');
  }

  async function checkout(plan: 'creator' | 'studio') {
    setWorking(true); setError('');
    try {
      const details = await api<Checkout>('/api/billing/checkout', { method: 'POST', body: JSON.stringify({ plan }) });
      await loadRazorpay();
      const instance = new window.Razorpay({
        key: details.key_id,
        subscription_id: details.subscription_id,
        name: 'Videomemory',
        description: `${plan[0].toUpperCase()}${plan.slice(1)} monthly plan`,
        prefill: details.customer,
        theme: { color: '#0a0b0c' },
        handler: async (payment: Record<string, string>) => {
          await api('/api/billing/verify', { method: 'POST', body: JSON.stringify(payment) });
          setNotice('Payment verified. Your plan will update as soon as Razorpay confirms the subscription.');
          window.setTimeout(refresh, 1500);
        },
      });
      instance.open();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Checkout could not start'); }
    finally { setWorking(false); }
  }

  async function cancelPlan() {
    if (!window.confirm('Cancel at the end of your current billing period? Your plan stays active until then.')) return;
    setWorking(true); setError('');
    try {
      await api('/api/billing/cancel', { method: 'POST', body: '{}' });
      setNotice('Cancellation scheduled. Your paid limits remain active through the current period.');
      await refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not cancel the plan'); }
    finally { setWorking(false); }
  }

  async function createNote(event: FormEvent) {
    event.preventDefault();
    setWorking(true); setError('');
    try {
      await api('/api/memory/notes', {
        method: 'POST',
        body: JSON.stringify({ video_id: noteVideo, title: noteTitle, body: noteBody, parent_note_id: noteParent || undefined }),
      });
      setNoteTitle(''); setNoteBody(''); setNoteParent('');
      setNotice('Note added to the graph. The earlier branch remains intact.');
      await loadMemory();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save this note'); }
    finally { setWorking(false); }
  }

  async function openVideo(videoId: string) {
    setWorking(true); setError(''); setVideoHits([]);
    try { setSelectedVideo(await api<VideoDetail>(`/api/videos/${encodeURIComponent(videoId)}`)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not open this video'); }
    finally { setWorking(false); }
  }

  async function askVideo(event: FormEvent) {
    event.preventDefault();
    if (!selectedVideo || !videoQuestion.trim()) return;
    setWorking(true); setError('');
    try {
      const result = await api<{ hits: VideoHit[] }>(`/api/videos/${encodeURIComponent(selectedVideo.video.video_id)}/ask`, {
        method: 'POST', body: JSON.stringify({ question: videoQuestion }),
      });
      setVideoHits(result.hits);
      if (!result.hits.length) setNotice('No spoken transcript matched. Try a broader phrase or use the MCP visual tools.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not search this video'); }
    finally { setWorking(false); }
  }

  async function removeVideo(videoId: string) {
    if (!window.confirm('Delete this video, transcript, frames, notes, and graph relationships? This cannot be undone.')) return;
    setWorking(true); setError('');
    try {
      await api(`/api/videos/${encodeURIComponent(videoId)}`, { method: 'DELETE' });
      setSelectedVideo(null); setVideoHits([]); setNotice('Video and its memory were deleted.');
      await refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not delete this video'); }
    finally { setWorking(false); }
  }

  async function testConnection() {
    setConnectionStatus('checking'); setError('');
    try {
      const result = await api<{ status: string; checks: Record<string, boolean> }>('/health');
      if (result.status !== 'ok' || !Object.values(result.checks).every(Boolean)) throw new Error('API is not ready');
      setConnectionStatus('healthy'); setNotice('API, database, and storage checks passed. Your MCP endpoint is ready.');
    } catch (caught) {
      setConnectionStatus('failed'); setError(caught instanceof Error ? caught.message : 'Connection test failed');
    }
  }

  async function createArtifact(event: FormEvent) {
    event.preventDefault(); setWorking(true); setError('');
    try {
      await api('/api/artifacts', { method: 'POST', body: JSON.stringify({ title: artifactTitle, locator: artifactLocator, summary: artifactSummary, project: artifactProject, kind: artifactKind, access_instructions: 'Open the recorded locator from an authorized workspace.' }) });
      setArtifactTitle(''); setArtifactLocator(''); setArtifactSummary('');
      const result = await api<{ artifacts: Artifact[] }>('/api/artifacts'); setArtifacts(result.artifacts);
      setNotice('Artifact remembered. Connected agents can recall it through MCP.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not remember this artifact'); }
    finally { setWorking(false); }
  }

  if (loading) {
    return <main className="dashboard-loading"><Mark /><p>Opening your memory…</p></main>;
  }
  if (!account) {
    return <main className="dashboard-loading"><Mark /><p>{error || 'Account unavailable'}</p><a href="/login">Sign in</a></main>;
  }

  const firstName = account.user.name.split(' ')[0];
  return (
    <main className="dashboard-shell">
      <aside className="dash-sidebar">
        <Brand />
        <nav aria-label="Dashboard navigation">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button className={section === id ? 'active' : ''} key={id} onClick={() => setSection(id)} aria-label={label}>
              <Icon aria-hidden="true" size={17} strokeWidth={1.7} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="plan-badge"><span className="status-dot" /><div><small>PLAN</small><strong>{account.user.plan}</strong></div></div>
          <button onClick={logout}><LogOut aria-hidden="true" size={15} />Sign out</button>
        </div>
      </aside>

      <section className="dash-main">
        <header className="dash-header">
          <div><p>{section.toUpperCase()}</p><h1>{section === 'overview' ? `Good to see you, ${firstName}.` : section === 'library' ? 'Your video memory.' : section === 'memory' ? 'Your context brain.' : section === 'artifacts' ? 'Everything your agents made.' : section === 'connections' ? 'Connect your agents.' : 'Plan and usage.'}</h1></div>
          <div className="profile-chip"><span>{firstName.slice(0, 1).toUpperCase()}</span><div><strong>{account.user.name}</strong><small>{account.user.email}</small></div></div>
          <button className="mobile-signout" aria-label="Sign out" onClick={logout}><LogOut size={17} /></button>
        </header>

        {(error || notice) && <div className={error ? 'dash-alert error' : 'dash-alert'}>{error || notice}<button aria-label="Dismiss message" onClick={() => { setError(''); setNotice(''); }}><X size={16} /></button></div>}

        {section === 'overview' && (
          <div className="dash-content">
            <div className="usage-grid">
              {stats.map(([label, value, limit]) => (
                <article className="usage-card" key={label}>
                  <div><span>{label}</span><em>THIS MONTH</em></div>
                  <strong>{value.toLocaleString()}</strong><small>/ {limit.toLocaleString()}</small>
                  <div className="usage-track"><i style={{ width: `${Math.min(100, (value / limit) * 100)}%` }} /></div>
                </article>
              ))}
            </div>

            <div className="ingest-grid">
              <form className="add-video-card" onSubmit={addVideo}>
                <div className="add-icon"><Link2 aria-hidden="true" size={21} /></div>
                <div><span className="ingest-label">PUBLIC LINK</span><h2>Add by URL</h2><p>Paste a supported public video page or direct media URL. Private networks are blocked before download.</p></div>
                <div className="url-control"><input type="url" required value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="https://youtube.com/watch?v=…" aria-label="Public video URL" /><button type="submit" disabled={working}>Index video <ArrowUpRight aria-hidden="true" size={15} /></button></div>
              </form>
              <form className="add-video-card upload-video-card" onSubmit={uploadVideo}>
                <div className="add-icon"><Upload aria-hidden="true" size={21} /></div>
                <div><span className="ingest-label">PRIVATE FILE</span><h2>Upload a video</h2><p>MP4, MOV, WebM, MKV, MP3, M4A, or WAV. Files stay inside your tenant workspace.</p></div>
                <div className="file-control">
                  <label><FileVideo aria-hidden="true" size={16} /><span>{uploadFile ? uploadFile.name : 'Choose a media file · 100 MB max'}</span><input key={uploadInputKey} type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,audio/mpeg,audio/mp4,audio/wav" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} /></label>
                  <button type="submit" disabled={working || !uploadFile}>Upload &amp; index <ArrowUpRight aria-hidden="true" size={15} /></button>
                </div>
              </form>
            </div>

            <div className="dash-split">
              <section className="activity-panel">
                <div className="panel-head"><div><span>PROCESSING ACTIVITY</span><small>Live</small></div><button onClick={() => setSection('library')}>View library <ArrowUpRight aria-hidden="true" size={12} /></button></div>
                <div className="job-list">
                  {account.jobs.length === 0 && <div className="empty-row">Add your first video to see real processing activity here.</div>}
                  {account.jobs.slice(0, 5).map((job) => (
                    <div className="job-row" key={job.job_id}>
                      <span className={`job-state ${job.status}`} />
                      <div><strong>{sourceLabel(job.source)}</strong><small>{job.error || (job.source.length > 58 ? `${job.source.slice(0, 58)}…` : job.source)}</small></div>
                      <em>{job.status}</em>
                      <div className="job-progress"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
                      <time>{relativeTime(job.created_at)}</time>
                    </div>
                  ))}
                </div>
              </section>
              <section className="connection-panel">
                <div className="panel-head"><div><span>MCP CONNECTION</span><small>{account.api_keys.length} active</small></div></div>
                <div className="connection-orbit"><Mark /><span className="connection-pulse" /></div>
                <h3>{connectionStatus === 'healthy' ? 'Endpoint verified.' : 'Connect your first agent.'}</h3><p>{connectionStatus === 'healthy' ? 'API, database, and storage checks passed.' : 'Open the guide, then run the built-in readiness check.'}</p>
                <button onClick={() => setSection('connections')}>Open connection guide <ArrowUpRight aria-hidden="true" size={12} /></button>
              </section>
            </div>
          </div>
        )}

        {section === 'library' && (
          <div className="dash-content">
            <div className="library-ingest-row">
              <form className="compact-add" onSubmit={addVideo}><input aria-label="Paste a public video URL" type="url" required value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="Paste a public video URL" /><button disabled={working}>Index link <ArrowUpRight aria-hidden="true" size={14} /></button></form>
              <form className="compact-upload" onSubmit={uploadVideo}><label><Upload aria-hidden="true" size={15} /><span>{uploadFile ? uploadFile.name : 'Choose file'}</span><input key={uploadInputKey} aria-label="Upload a video file" type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,audio/mpeg,audio/mp4,audio/wav" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} /></label><button disabled={working || !uploadFile}>Upload</button></form>
            </div>
            <div className="library-grid">
              {account.videos.length === 0 && <div className="library-empty"><Mark /><h2>No memories yet.</h2><p>Paste a video URL above. Transcript, visual index, and key moments will appear here.</p></div>}
              {account.videos.map((video, index) => (
                <button className="video-card" key={video.video_id} onClick={() => openVideo(video.video_id)} aria-label={`Open ${video.title || 'indexed video'}`}>
                  <div className={`video-preview tone-${index % 3}`}><span className="video-time">{formatDuration(video.duration)}</span><div className="video-scan" /></div>
                  <div className="video-meta"><span>{sourceLabel(video.source)}</span><h3>{video.title || 'Indexed video'}</h3><p>Added {relativeTime(video.added_at)} · Open memory</p></div>
                </button>
              ))}
            </div>
            {selectedVideo && (
              <section className="video-detail" aria-label="Video memory detail">
                <div className="video-detail-head">
                  <div><span className="section-kicker">VIDEO MEMORY</span><h2>{selectedVideo.video.title || 'Indexed video'}</h2><p>{formatDuration(selectedVideo.video.duration)} · {selectedVideo.transcript.length} transcript windows · {sourceLabel(selectedVideo.video.source)}</p></div>
                  <div><button className="detail-danger" onClick={() => removeVideo(selectedVideo.video.video_id)} disabled={working}><Trash2 size={14} /> Delete</button><button className="detail-close" onClick={() => setSelectedVideo(null)} aria-label="Close video detail"><X size={17} /></button></div>
                </div>
                <form className="video-ask" onSubmit={askVideo}>
                  <Search aria-hidden="true" size={17} />
                  <input value={videoQuestion} onChange={(event) => setVideoQuestion(event.target.value)} placeholder="Ask where something was said…" aria-label="Search this video's transcript" />
                  <button disabled={working || !videoQuestion.trim()}>Find exact moments <ArrowUpRight size={14} /></button>
                </form>
                {videoHits.length > 0 && <div className="moment-results">{videoHits.map((hit, index) => <article key={`${hit.start}-${index}`}><time>{hit.timestamp_human}</time><p>{hit.transcript_excerpt}</p><span>{Math.round(hit.score * 100)}% match</span>{hit.deep_link && <a href={hit.deep_link} target="_blank" rel="noreferrer">Open source <ArrowUpRight size={11} /></a>}</article>)}</div>}
                <div className="transcript-list">
                  <div className="panel-head"><div><span>TRANSCRIPT</span><small>{selectedVideo.transcript.length ? 'Indexed and searchable' : 'No spoken audio detected'}</small></div></div>
                  {selectedVideo.transcript.slice(0, 12).map((window) => <article key={window.window_id}><time>{formatDuration(window.start)}</time><p>{window.text}</p></article>)}
                  {selectedVideo.transcript.length > 12 && <p className="transcript-more">Showing the first 12 windows. Search above to jump across the full transcript.</p>}
                </div>
              </section>
            )}
          </div>
        )}

        {section === 'memory' && (
          <div className="dash-content memory-content">
            <section className="memory-intro">
              <div><p className="section-kicker">LIVING CONTEXT GRAPH</p><h2>Everything you explore<br />strengthens the next answer.</h2><p>Queries, videos, exact moments, and branched notes become durable relationships. Repeated paths grow stronger; earlier interpretations are never overwritten.</p></div>
              <div className="memory-totals"><div><strong>{memory?.nodes.length || 0}</strong><span>NODES</span></div><div><strong>{memory?.edges.length || 0}</strong><span>RELATIONS</span></div><div><strong>{memory?.notes.length || 0}</strong><span>NOTES</span></div></div>
            </section>
            <div className="memory-layout">
              <section className="graph-panel">
                <div className="panel-head"><div><span>CONTEXT MAP</span><small>Private · live</small></div><button onClick={loadMemory}>Refresh <RefreshCw aria-hidden="true" size={11} /></button></div>
                <div className="graph-stage">
                  <div className="graph-core"><Mark /><span>YOU</span></div>
                  {!memory?.nodes.length && <div className="graph-empty">Your first video query will light up this graph.</div>}
                  {memory?.nodes.slice(0, 18).map((node, index) => {
                    const angle = (index / Math.min(memory.nodes.length, 18)) * Math.PI * 2 - Math.PI / 2;
                    const ring = index % 3 === 0 ? 34 : index % 2 === 0 ? 42 : 46;
                    const x = 50 + Math.cos(angle) * ring;
                    const y = 50 + Math.sin(angle) * ring * .82;
                    const dx = 50 - x; const dy = 50 - y;
                    const style = { '--gx': `${x}%`, '--gy': `${y}%`, '--gl': `${Math.sqrt(dx * dx + dy * dy) * 5.1}px`, '--ga': `${Math.atan2(dy, dx)}rad` } as CSSProperties;
                    return <div className={`graph-node ${node.node_type}`} style={style} key={node.node_id} title={`${node.node_type}: ${node.label}`}><i /><span>{node.label.length > 24 ? `${node.label.slice(0, 24)}…` : node.label}</span><em>{node.node_type}</em></div>;
                  })}
                </div>
              </section>
              <aside className="memory-side">
                <section className="relation-feed"><div className="panel-head"><div><span>STRONGEST PATHS</span></div></div><div>{memory?.edges.slice(0, 7).map((edge) => <article key={edge.edge_id}><span>{edge.relation.replaceAll('_', ' ')}</span><strong>×{Math.round(edge.weight)}</strong><small>{relativeTime(edge.updated_at)}</small></article>)}{memory && memory.edges.length === 0 && <p>No paths yet. Ask your agent about a video.</p>}</div></section>
                <form className="note-compose" onSubmit={createNote}>
                  <p className="section-kicker">BRANCH A THOUGHT</p><h3>Attach a note.</h3>
                  <select aria-label="Video for this note" required value={noteVideo} onChange={(event) => { setNoteVideo(event.target.value); setNoteParent(''); }}><option value="">Choose a video</option>{account.videos.map((video) => <option value={video.video_id} key={video.video_id}>{video.title || video.source}</option>)}</select>
                  <select aria-label="Parent note branch" value={noteParent} onChange={(event) => setNoteParent(event.target.value)}><option value="">New root note</option>{memory?.notes.filter((note) => !noteVideo || note.video_id === noteVideo).map((note) => <option value={note.note_id} key={note.note_id}>Branch v{note.version}: {note.title}</option>)}</select>
                  <input aria-label="Note title" required maxLength={160} value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="What changed in my thinking?" />
                  <textarea aria-label="Note body" required maxLength={20000} value={noteBody} onChange={(event) => setNoteBody(event.target.value)} placeholder="Capture the idea, decision, or connection…" />
                  <button disabled={working || account.videos.length === 0}>Save to graph <Check aria-hidden="true" size={14} /></button>
                </form>
              </aside>
            </div>
            <section className="note-history"><div className="panel-head"><div><span>NOTE BRANCHES</span><small>Versioned, never overwritten</small></div></div><div className="note-grid">{memory?.notes.map((note) => <article key={note.note_id}><div><span>v{note.version}</span>{note.parent_note_id && <em>BRANCH</em>}</div><h3>{note.title}</h3><p>{note.body}</p><small>{relativeTime(note.created_at)}</small></article>)}{memory && memory.notes.length === 0 && <p className="empty-note">No notes yet. Branch your first thought from a remembered video.</p>}</div></section>
          </div>
        )}

        {section === 'connections' && (
          <div className="dash-content connections-content">
            {newKey && <div className="new-key-callout"><div><KeyRound aria-hidden="true" size={13} /> COPY THIS KEY NOW</div><code>{newKey}</code><button onClick={copyKey}><Copy aria-hidden="true" size={13} />Copy key</button><p>It will not be shown again.</p></div>}
            <section className="connection-guide">
              <div className="guide-copy"><p className="section-kicker">STREAMABLE HTTP</p><h2>One secure endpoint.<br />Every video tool.</h2><p>Your MCP key selects only your tenant before any tool runs. Use a separate key for each environment so you can revoke access without disrupting everything.</p><div className="endpoint-field"><small>ENDPOINT</small><code>{MCP_URL}</code></div><button className={`connection-test ${connectionStatus}`} onClick={testConnection} disabled={connectionStatus === 'checking'}><PlugZap size={14} />{connectionStatus === 'checking' ? 'Checking…' : connectionStatus === 'healthy' ? 'Verified healthy' : connectionStatus === 'failed' ? 'Retry connection test' : 'Test connection'}</button></div>
              <div className="install-stack">
                <article><span>CLAUDE CODE</span><pre>claude mcp add --transport http videomemory {MCP_URL} \{`\n`}  --header &quot;Authorization: Bearer vm_live_••••&quot;</pre></article>
                <article><span>CODEX · config.toml</span><pre>[mcp_servers.videomemory]{`\n`}url = &quot;{MCP_URL}&quot;{`\n`}bearer_token_env_var = &quot;VIDEOMEMORY_TOKEN&quot;</pre></article>
              </div>
            </section>
            <section className="keys-panel">
              <div className="panel-head"><div><span>API KEYS</span><small>Secrets are hashed at rest</small></div></div>
              <form className="key-create" onSubmit={createKey}><input value={keyName} maxLength={80} onChange={(event) => setKeyName(event.target.value)} aria-label="New API key name" /><button disabled={working}>Create key <Plus aria-hidden="true" size={14} /></button></form>
              <div className="keys-table">
                {account.api_keys.map((key) => <div key={key.prefix}><div><strong>{key.name}</strong><code>{key.prefix}••••••••</code></div><span>Last used {relativeTime(key.last_used_at)}</span><time>Created {relativeTime(key.created_at)}</time><button onClick={() => revokeKey(key.prefix)}>Revoke</button></div>)}
              </div>
            </section>
          </div>
        )}

        {section === 'artifacts' && (
          <div className="dash-content artifact-content">
            <section className="artifact-hero">
              <div><p className="section-kicker">ORGANIZATION MEMORY</p><h2>Never lose an<br />agent-made artifact.</h2><p>Codex, Claude, Cursor, and your team can remember where an artifact lives, what it contains, how to open it, and which version or project it belongs to.</p></div>
              <div className="artifact-count"><strong>{artifacts.length}</strong><span>REMEMBERED</span></div>
            </section>
            <form className="artifact-form" onSubmit={createArtifact}>
              <div className="panel-head"><div><span>REMEMBER AN ARTIFACT</span><small>Agents can also call remember_artifact automatically</small></div></div>
              <div className="artifact-fields">
                <input required maxLength={240} value={artifactTitle} onChange={(event) => setArtifactTitle(event.target.value)} placeholder="Artifact title" aria-label="Artifact title" />
                <select value={artifactKind} onChange={(event) => setArtifactKind(event.target.value)} aria-label="Artifact kind"><option value="code">Code</option><option value="document">Document</option><option value="design">Design</option><option value="image">Image</option><option value="video">Video</option><option value="dataset">Dataset</option><option value="report">Report</option><option value="other">Other</option></select>
                <input required maxLength={2048} value={artifactLocator} onChange={(event) => setArtifactLocator(event.target.value)} placeholder="Path, repository URL, document URL, or durable ID" aria-label="Artifact locator" />
                <input maxLength={240} value={artifactProject} onChange={(event) => setArtifactProject(event.target.value)} placeholder="Project / workspace" aria-label="Artifact project" />
                <textarea maxLength={10000} value={artifactSummary} onChange={(event) => setArtifactSummary(event.target.value)} placeholder="What it is, why it exists, and how another teammate should use it…" aria-label="Artifact summary" />
                <button disabled={working}>Remember artifact <Plus size={14} /></button>
              </div>
            </form>
            <section className="artifact-list">
              <div className="panel-head"><div><span>ARTIFACT MEMORY</span><small>Versioned · tenant private · MCP searchable</small></div></div>
              {!artifacts.length && <div className="artifact-empty"><PackageOpen size={25} /><h3>No artifacts remembered yet.</h3><p>Add one above or ask a connected agent to call remember_artifact after it creates something useful.</p></div>}
              <div className="artifact-grid">{artifacts.map((artifact) => <article key={artifact.artifact_id}><div><span>{artifact.kind}</span><em>v{artifact.version}</em></div><h3>{artifact.title}</h3><p>{artifact.summary || 'No summary recorded yet.'}</p><code>{artifact.locator}</code><div className="artifact-meta"><span>{artifact.project || 'No project'}</span><time>{relativeTime(artifact.updated_at)}</time></div></article>)}</div>
            </section>
          </div>
        )}

        {section === 'billing' && (
          <div className="dash-content billing-content">
            <section className="current-plan"><div><p className="section-kicker">CURRENT PLAN</p><h2>{account.user.plan[0].toUpperCase()}{account.user.plan.slice(1)}</h2><p>{account.user.plan === 'free' ? 'A useful place to begin. Upgrade when Videomemory becomes part of your weekly workflow.' : 'Your paid plan is active and applied to this month’s usage.'}</p>{account.user.plan !== 'free' && <button className="cancel-plan" disabled={working} onClick={cancelPlan}>Cancel at period end</button>}</div><div className="billing-mark"><Mark /></div></section>
            <div className="billing-plan-grid">
              {(['free', 'creator', 'studio'] as const).map((plan) => {
                const prices = { free: 0, creator: 12, studio: 29 };
                const selected = account.user.plan === plan;
                return <article className={selected ? 'billing-plan selected' : 'billing-plan'} key={plan}><div><span>{plan.toUpperCase()}</span>{selected && <em>CURRENT</em>}</div><strong>${prices[plan]}<small>/mo</small></strong><ul><li>{PLAN_COPY[plan][0]}</li><li>{PLAN_COPY[plan][1]}</li><li>{PLAN_COPY[plan][2]}</li></ul>{plan === 'free' ? <button disabled>Included</button> : <button disabled={selected || working || !account.billing.enabled} onClick={() => checkout(plan)}>{selected ? 'Current plan' : account.billing.enabled ? `Choose ${plan}` : 'Payments opening soon'}</button>}</article>;
              })}
            </div>
            {!account.billing.enabled && <div className="billing-note"><CreditCard aria-hidden="true" size={17} /><p>Paid upgrades are temporarily unavailable. You can keep using the Free plan while checkout is being connected.</p></div>}
          </div>
        )}
      </section>
    </main>
  );
}

const PLAN_COPY = {
  free: ['5 videos / month', '60 indexed minutes', '200 MCP calls'],
  creator: ['100 videos / month', '1,200 indexed minutes', '5,000 MCP calls'],
  studio: ['1,000 videos / month', '10,000 indexed minutes', '50,000 MCP calls'],
};
