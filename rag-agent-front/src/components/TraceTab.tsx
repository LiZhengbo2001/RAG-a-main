import { memo } from 'react';
import type { TraceStep } from '../types';

interface TraceTabProps { steps: TraceStep[] | null; }

const phaseStyle: Record<TraceStep['phase'], { bg: string; text: string }> = {
  planning:   { bg: 'bg-violet-100', text: 'text-violet-600' },
  retrieval:  { bg: 'bg-primary-100', text: 'text-primary-600' },
  generation: { bg: 'bg-emerald-100', text: 'text-emerald-600' },
};

const labelStyle: Record<TraceStep['phase'], string> = {
  planning: 'text-violet-600', retrieval: 'text-primary-600', generation: 'text-emerald-600',
};

export default memo(function TraceTab({ steps }: TraceTabProps) {
  if (!steps || steps.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-ink-muted gap-2">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          className="opacity-20" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
        <p className="text-xs">暂无推理记录</p>
      </div>
    );
  }

  return (
    <div className="relative pl-1">
      <div className="absolute left-[13px] top-2 bottom-2 w-px bg-surface-border" />
      <div className="space-y-4">
        {steps.map((step, i) => {
          const s = phaseStyle[step.phase];
          return (
            <div key={i} className="flex gap-4 animate-slide-left" style={{ animationDelay: `${i * 80}ms` }}>
              <div className={`relative z-10 flex-shrink-0 w-[27px] h-[27px] rounded-full ${s.bg} ring-1 ring-black/5 flex items-center justify-center font-mono text-[11px] font-semibold ${s.text}`}>
                {i + 1}
              </div>
              <div className="flex-1 min-w-0 pt-0.5">
                <div className={`text-[11px] font-semibold uppercase tracking-wider mb-1 ${labelStyle[step.phase]}`}>
                  {step.label}
                </div>
                <p className="text-[12px] text-ink-body leading-relaxed">{step.detail}</p>
                <span className="text-[10px] text-ink-dim font-mono mt-1 inline-block">{step.time}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
});
