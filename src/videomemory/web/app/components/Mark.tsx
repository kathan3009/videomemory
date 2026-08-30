import Link from 'next/link';

export function Mark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={compact ? 'mark mark-compact' : 'mark'} aria-hidden="true">
      <span className="mark-frame mark-frame-back" />
      <span className="mark-frame mark-frame-mid" />
      <span className="mark-frame mark-frame-front"><i /></span>
    </span>
  );
}

export function Brand() {
  return (
    <Link className="brand" href="/" aria-label="VideoMemory home">
      <Mark />
      <span>VideoMemory</span>
    </Link>
  );
}
