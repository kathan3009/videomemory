export const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080').replace(/\/$/, '');

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = typeof window !== 'undefined' ? window.localStorage.getItem('vm_session') : null;
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(session ? { 'X-Videomemory-Session': session } : {}),
      ...options.headers,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') window.localStorage.removeItem('vm_session');
    throw new Error(payload.error || 'Request failed');
  }
  if (payload.session_token && typeof window !== 'undefined') {
    window.localStorage.setItem('vm_session', payload.session_token);
  }
  return payload as T;
}
