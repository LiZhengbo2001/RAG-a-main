import { memo, useState } from 'react';
import type { Source } from '../types';

interface Props {
  sources: Source[];
}

export default memo(function RetrievalDetail({ sources }: Props) {
  const [open, setOpen] = useState(false);

  if (!sources || sources.length === 0) return null;

  const hasRerank = sources.some(s => s.rerank_score !== undefined);

  return (
    <div className="border border-surface-border rounded-xl overflow-hidden bg-white mt-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2.5 w-full px-4 py-2.5 bg-surface-muted hover:bg-surface-hover transition-colors cursor-pointer select-none"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          className={`text-primary-500 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}>
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="text-xs font-medium text-primary-600">
          检索详情 ({sources.length} 条命中)
        </span>
        {hasRerank && (
          <span className="text-[10px] text-ink-muted ml-1">含重排分</span>
        )}
      </button>
      <div className={`overflow-hidden transition-all duration-300 ${open ? 'max-h-[600px] opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="divide-y divide-surface-border max-h-[400px] overflow-y-auto scrollbar-thin">
          {sources.map((s, i) => (
            <div key={s.id} className="px-4 py-3 animate-slide-left" style={{ animationDelay: `${i * 40}ms` }}>
              {/* 标题行 */}
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-primary-50 text-primary-600 flex items-center justify-center text-[10px] font-mono font-semibold">
                    {s.id}
                  </span>
                  <span className="text-[13px] font-medium text-ink-strong truncate leading-snug">
                    {s.title}
                  </span>
                </div>
                {/* 评分区 */}
                <div className="flex flex-shrink-0 items-center gap-1.5">
                  <span className="text-[11px] font-mono text-ink-muted whitespace-nowrap">
                    RRF {(s.score * 100).toFixed(0)}%
                  </span>
                  {s.rerank_score !== undefined && (
                    <span className="text-[11px] font-mono whitespace-nowrap px-1.5 py-0.5 rounded-md bg-emerald-50 text-emerald-600 font-semibold">
                      ★ {s.rerank_score}
                    </span>
                  )}
                </div>
              </div>
              {/* 摘要 */}
              {s.excerpt && (
                <p className="text-[11px] text-ink-muted leading-relaxed ml-7 line-clamp-2">
                  {s.excerpt}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
