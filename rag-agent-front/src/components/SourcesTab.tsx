import { memo, useRef, useEffect } from 'react';
import type { Source } from '../types';

interface SourcesTabProps {
  sources: Source[] | null;
  highlightedId: number | null;
}

export default memo(function SourcesTab({ sources, highlightedId }: SourcesTabProps) {
  if (!sources || sources.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-ink-muted gap-2">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          className="opacity-20" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <p className="text-xs">暂无检索来源</p>
      </div>
    );
  }

  return (
    <div className="grid gap-2.5 sm:grid-cols-2">
      {sources.map(s => (
        <SourceCard key={s.id} source={s} highlighted={highlightedId === s.id} />
      ))}
    </div>
  );
});

function SourceCard({ source, highlighted }: { source: Source; highlighted: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [highlighted]);

  return (
    <div ref={ref}
      className={`p-4 rounded-xl border transition-all duration-300 bg-white
        ${highlighted
          ? 'border-primary-400 shadow-md shadow-primary-100'
          : 'border-surface-border hover:border-primary-200 hover:-translate-y-0.5'
        }`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <h4 className="text-sm font-medium text-ink-strong leading-snug flex-1">{source.title}</h4>
        <span className={`flex-shrink-0 text-[11px] font-mono font-medium px-2 py-0.5 rounded-full
          ${source.score >= 0.85 ? 'bg-emerald-50 text-emerald-600' : 'bg-primary-50 text-primary-600'}`}>
          {(source.score * 100).toFixed(0)}%
        </span>
      </div>
      {(source.author || source.year) && (
        <div className="flex items-center gap-2 text-[11px] text-ink-muted mb-2">
          {source.author && <span>{source.author}</span>}
          {source.author && source.year && <span>·</span>}
          {source.year && <span>{source.year}</span>}
        </div>
      )}
      {source.excerpt && (
        <p className="text-[12px] text-ink-body leading-relaxed line-clamp-3">{source.excerpt}</p>
      )}
      {source.url && (
        <a href={source.url} target="_blank" rel="noopener noreferrer"
          className="inline-block mt-2 text-[11px] text-primary-500 hover:text-primary-700 transition-colors">
          查看原文 →
        </a>
      )}
    </div>
  );
}
