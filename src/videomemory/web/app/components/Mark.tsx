import Link from 'next/link';

export function Mark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={compact ? 'mark mark-compact' : 'mark'} aria-hidden="true">
      <span className="mark-ring mark-ring-a" />
      <span className="mark-ring mark-ring-b" />
      <span className="mark-core" />
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
