'use client';

import { CSSProperties, FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Brand, Mark } from '../components/Mark';
import { api } from '../lib/api';

type User = { user_id: string; name: string; email: string; plan: 'free' | 'creator' | 'studio'; created_at: string };
type Usage = { plan: string; limits: Record<string, number>; totals: Record<string, number>; period_start: string };
type Video = { video_id: string; source: string; title?: string; duration: number; added_at: string };
type Job = { job_id: string; source: string; status: string; progress: number; error?: string; created_at: string };
type ApiKey = { name: string; prefix: string; created_at: string; last_used_at?: string };
type MemoryNode = { node_id: string; node_type: 'video' | 'query' | 'moment' | 'note'; label: string; access_count: number; properties: Record<string, unknown>; updated_at: string };
type MemoryEdge = { edge_id: string; source_id: string; target_id: string; relation: string; weight: number; updated_at: string };
type MemoryNote = { note_id: string; video_id: string; parent_note_id?: string; title: string; body: string; version: number; created_at: string };
type MemoryGraph = { nodes: MemoryNode[]; edges: MemoryEdge[]; events: { event_id: string; tool: string; query?: string; video_id?: string; created_at: string }[]; notes: MemoryNote[] };
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

const MCP_URL = process.env.NEXT_PUBLIC_MCP_URL || 'https://mcp.videomemory.ai/mcp';

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
  const [section, setSection] = useState<'overview' | 'library' | 'memory' | 'connections' | 'billing'>('overview');
  const [videoUrl, setVideoUrl] = useState('');
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
    await api(`/api/keys/${encodeURIComponent(prefix)}`, { method: 'DELETE' });
    await refresh();
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST', body: '{}' });
    window.localStorage.removeItem('vm_session');
    router.push('/');
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
          {(['overview', 'library', 'memory', 'connections', 'billing'] as const).map((item) => (
            <button className={section === item ? 'active' : ''} key={item} onClick={() => setSection(item)}>
              <span>{item === 'overview' ? '⌁' : item === 'library' ? '▱' : item === 'memory' ? '✣' : item === 'connections' ? '◇' : '○'}</span>{item}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="plan-badge"><span className="status-dot" /><div><small>PLAN</small><strong>{account.user.plan}</strong></div></div>
          <button onClick={logout}>Sign out</button>
        </div>
      </aside>

      <section className="dash-main">
        <header className="dash-header">
          <div><p>{section.toUpperCase()}</p><h1>{section === 'overview' ? `Good to see you, ${firstName}.` : section === 'library' ? 'Your video memory.' : section === 'memory' ? 'Your context brain.' : section === 'connections' ? 'Connect your agents.' : 'Plan and usage.'}</h1></div>
          <div className="profile-chip"><span>{firstName.slice(0, 1).toUpperCase()}</span><div><strong>{account.user.name}</strong><small>{account.user.email}</small></div></div>
        </header>

        {(error || notice) && <div className={error ? 'dash-alert error' : 'dash-alert'}>{error || notice}<button onClick={() => { setError(''); setNotice(''); }}>×</button></div>}

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

            <form className="add-video-card" onSubmit={addVideo}>
              <div className="add-icon"><span>＋</span></div>
              <div><h2>Add to your memory</h2><p>Paste any public video page or direct media URL. Private networks are blocked before download.</p></div>
              <div className="url-control"><input type="url" required value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="https://youtube.com/watch?v=…" aria-label="Public video URL" /><button type="submit" disabled={working}>Index video <span>↗</span></button></div>
            </form>

            <div className="dash-split">
              <section className="activity-panel">
                <div className="panel-head"><div><span>PROCESSING ACTIVITY</span><small>Live</small></div><button onClick={() => setSection('library')}>View library ↗</button></div>
                <div className="job-list">
                  {account.jobs.length === 0 && <div className="empty-row">Add your first video to see real processing activity here.</div>}
                  {account.jobs.slice(0, 5).map((job) => (
                    <div className="job-row" key={job.job_id}>
                      <span className={`job-state ${job.status}`} />
                      <div><strong>{new URL(job.source).hostname}</strong><small>{job.source.length > 58 ? `${job.source.slice(0, 58)}…` : job.source}</small></div>
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
                <h3>Your endpoint is ready.</h3><p>Connect Claude or Codex with a private bearer token.</p>
                <button onClick={() => setSection('connections')}>Open connection guide <span>↗</span></button>
              </section>
            </div>
          </div>
        )}

        {section === 'library' && (
          <div className="dash-content">
            <form className="compact-add" onSubmit={addVideo}><input type="url" required value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="Paste a public video URL" /><button disabled={working}>Index <span>↗</span></button></form>
            <div className="library-grid">
              {account.videos.length === 0 && <div className="library-empty"><Mark /><h2>No memories yet.</h2><p>Paste a video URL above. Transcript, visual index, and key moments will appear here.</p></div>}
              {account.videos.map((video, index) => (
                <article className="video-card" key={video.video_id}>
                  <div className={`video-preview tone-${index % 3}`}><span className="video-time">{formatDuration(video.duration)}</span><div className="video-scan" /></div>
                  <div className="video-meta"><span>{new URL(video.source).hostname}</span><h3>{video.title || 'Indexed video'}</h3><p>Added {relativeTime(video.added_at)}</p></div>
                </article>
              ))}
            </div>
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
                <div className="panel-head"><div><span>CONTEXT MAP</span><small>Private · live</small></div><button onClick={loadMemory}>Refresh ↻</button></div>
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
                  <select required value={noteVideo} onChange={(event) => setNoteVideo(event.target.value)}><option value="">Choose a video</option>{account.videos.map((video) => <option value={video.video_id} key={video.video_id}>{video.title || video.source}</option>)}</select>
                  <select value={noteParent} onChange={(event) => setNoteParent(event.target.value)}><option value="">New root note</option>{memory?.notes.filter((note) => !noteVideo || note.video_id === noteVideo).map((note) => <option value={note.note_id} key={note.note_id}>Branch v{note.version}: {note.title}</option>)}</select>
                  <input required maxLength={160} value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="What changed in my thinking?" />
                  <textarea required maxLength={20000} value={noteBody} onChange={(event) => setNoteBody(event.target.value)} placeholder="Capture the idea, decision, or connection…" />
                  <button disabled={working || account.videos.length === 0}>Save to graph <span>↗</span></button>
                </form>
              </aside>
            </div>
            <section className="note-history"><div className="panel-head"><div><span>NOTE BRANCHES</span><small>Versioned, never overwritten</small></div></div><div className="note-grid">{memory?.notes.map((note) => <article key={note.note_id}><div><span>v{note.version}</span>{note.parent_note_id && <em>BRANCH</em>}</div><h3>{note.title}</h3><p>{note.body}</p><small>{relativeTime(note.created_at)}</small></article>)}{memory && memory.notes.length === 0 && <p className="empty-note">No notes yet. Branch your first thought from a remembered video.</p>}</div></section>
          </div>
        )}

        {section === 'connections' && (
          <div className="dash-content connections-content">
            {newKey && <div className="new-key-callout"><div><span className="status-dot" /> COPY THIS KEY NOW</div><code>{newKey}</code><button onClick={() => navigator.clipboard.writeText(newKey)}>Copy key</button><p>It will not be shown again.</p></div>}
            <section className="connection-guide">
              <div className="guide-copy"><p className="section-kicker">STREAMABLE HTTP</p><h2>One secure endpoint.<br />Every video tool.</h2><p>Your MCP key selects only your tenant before any tool runs. Use a separate key for each environment so you can revoke access without disrupting everything.</p><div className="endpoint-field"><small>ENDPOINT</small><code>{MCP_URL}</code></div></div>
              <div className="install-stack">
                <article><span>CLAUDE CODE</span><pre>claude mcp add --transport http videomemory {MCP_URL} \{`\n`}  --header &quot;Authorization: Bearer vm_live_••••&quot;</pre></article>
                <article><span>CODEX · config.toml</span><pre>[mcp_servers.videomemory]{`\n`}url = &quot;{MCP_URL}&quot;{`\n`}bearer_token_env_var = &quot;VIDEOMEMORY_TOKEN&quot;</pre></article>
              </div>
            </section>
            <section className="keys-panel">
              <div className="panel-head"><div><span>API KEYS</span><small>Secrets are hashed at rest</small></div></div>
              <form className="key-create" onSubmit={createKey}><input value={keyName} maxLength={80} onChange={(event) => setKeyName(event.target.value)} aria-label="New API key name" /><button disabled={working}>Create key <span>＋</span></button></form>
              <div className="keys-table">
                {account.api_keys.map((key) => <div key={key.prefix}><div><strong>{key.name}</strong><code>{key.prefix}••••••••</code></div><span>Last used {relativeTime(key.last_used_at)}</span><time>Created {relativeTime(key.created_at)}</time><button onClick={() => revokeKey(key.prefix)}>Revoke</button></div>)}
              </div>
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
            {!account.billing.enabled && <div className="billing-note"><span>ℹ</span><p>Razorpay test keys have not been attached to this deployment yet. Plans and checkout are implemented; payment buttons activate automatically when the keys are configured.</p></div>}
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
