import { memo } from 'react';
import type { Source } from '../types';

interface SourceChipsProps {
  sources: Source[];
  onSourceClick: (id: number) => void;
}

export default memo(function SourceChips({ sources, onSourceClick }: SourceChipsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {sources.map(s => (
        <button
          key={s.id}
          onClick={() => onSourceClick(s.id)}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full
                     bg-primary-50 border border-primary-100
                     text-primary-600 text-[11px] font-medium
                     hover:bg-primary-500 hover:text-white hover:border-primary-500
                     transition-all duration-150 cursor-pointer"
        >
          <span className="font-mono text-[10px] opacity-70">[{s.id}]</span>
          <span className="truncate max-w-[140px]">
            {s.title.length > 18 ? s.title.slice(0, 18) + '…' : s.title}
          </span>
          <span className="font-mono text-[10px] opacity-60 ml-0.5">
            {(s.score * 100).toFixed(0)}%
          </span>
        </button>
      ))}
    </div>
  );
});
