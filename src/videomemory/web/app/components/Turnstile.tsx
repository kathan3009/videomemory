'use client';

import { useEffect, useRef } from 'react';

type TurnstileApi = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || '';
const SCRIPT_ID = 'videomemory-turnstile';

export function Turnstile({ action, onToken, resetSignal = 0 }: { action: string; onToken: (token: string) => void; resetSignal?: number }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!SITE_KEY || !host.current) return;
    let widgetId = '';
    let cancelled = false;
    let poll = 0;

    const render = () => {
      if (cancelled || !host.current || !window.turnstile || widgetId) return;
      widgetId = window.turnstile.render(host.current, {
        sitekey: SITE_KEY,
        theme: 'dark',
        size: 'flexible',
        action,
        callback: (token: string) => onToken(token),
        'expired-callback': () => onToken(''),
        'error-callback': () => onToken(''),
      });
    };

    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    const waitForApi = () => {
      render();
      if (!widgetId && !cancelled) poll = window.setTimeout(waitForApi, 100);
    };

    if (window.turnstile) render();
    else if (existing) waitForApi();
    else {
      const script = document.createElement('script');
      script.id = SCRIPT_ID;
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      script.async = true;
      script.defer = true;
      script.addEventListener('load', render, { once: true });
      document.head.appendChild(script);
    }

    return () => {
      cancelled = true;
      window.clearTimeout(poll);
      if (existing) existing.removeEventListener('load', render);
      if (widgetId && window.turnstile) window.turnstile.remove(widgetId);
    };
  }, [action, onToken, resetSignal]);

  if (!SITE_KEY) return null;
  return <div className="captcha-wrap"><div ref={host} /></div>;
}

export const captchaEnabled = Boolean(SITE_KEY);
