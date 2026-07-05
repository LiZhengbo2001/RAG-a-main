import { memo, useState } from 'react';
import type { ThinkingStep } from '../types';

interface Props {
  steps: ThinkingStep[];
  defaultOpen?: boolean;
}

const iconMap: Record<ThinkingStep['type'], { emoji: string }> = {
  search:   { emoji: 'Q' },
  result:   { emoji: 'R' },
  generate: { emoji: 'G' },
};

const bgMap: Record<ThinkingStep['type'], string> = {
  search:   'bg-violet-100 text-violet-600',
  result:   'bg-blue-100 text-blue-600',
  generate: 'bg-emerald-100 text-emerald-600',
};

export default memo(function ThinkingSteps({ steps, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border border-surface-border rounded-xl overflow-hidden bg-white">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2.5 w-full px-4 py-2.5 bg-surface-muted hover:bg-surface-hover transition-colors cursor-pointer select-none"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          className={`text-primary-500 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}>
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="text-xs font-medium text-primary-600">推理过程 ({steps.length} 步)</span>
      </button>
      <div className={`overflow-hidden transition-all duration-300 ${open ? 'max-h-[600px] opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="divide-y divide-surface-border">
          {steps.map((step, i) => (
            <div key={i} className="flex items-start gap-3 px-4 py-3 animate-slide-left"
              style={{ animationDelay: `${i * 60}ms` }}>
              <span className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono font-semibold ${bgMap[step.type]}`}>
                {iconMap[step.type].emoji}
              </span>
              <span className="text-[13px] text-ink-body leading-relaxed pt-px">{step.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
