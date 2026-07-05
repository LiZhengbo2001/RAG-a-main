import { memo } from 'react';
import type { PanelTab, Source, TraceStep } from '../types';
import SourcesTab from './SourcesTab';
import TraceTab from './TraceTab';

interface ContextPanelProps {
  open: boolean;
  activeTab: PanelTab;
  onTabChange: (tab: PanelTab) => void;
  sources: Source[] | null;
  trace: TraceStep[] | null;
  highlightedSource: number | null;
}

export default memo(function ContextPanel({
  open,
  activeTab,
  onTabChange,
  sources,
  trace,
  highlightedSource,
}: ContextPanelProps) {
  return (
    <aside
      className={`flex flex-col bg-surface border-l border-base-750 overflow-hidden transition-all duration-300
        max-[900px]:fixed max-[900px]:right-0 max-[900px]:top-[53px] max-[900px]:bottom-0 max-[900px]:z-50 max-[900px]:w-[340px] max-[900px]:shadow-2xl
        ${open ? 'w-[380px] min-w-[380px]' : 'w-0 min-w-0 border-l-0'}
        ${open ? 'max-[900px]:translate-x-0' : 'max-[900px]:translate-x-full'}`}
    >
      {/* Tabs */}
      <div className="flex border-b border-base-750 flex-shrink-0">
        <TabButton
          active={activeTab === 'sources'}
          onClick={() => onTabChange('sources')}
          label="检索来源"
          count={sources?.length ?? 0}
        />
        <TabButton
          active={activeTab === 'trace'}
          onClick={() => onTabChange('trace')}
          label="推理过程"
          count={trace?.length ?? 0}
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto scrollbar-thin p-5">
        {activeTab === 'sources' ? (
          <SourcesTab sources={sources} highlightedId={highlightedSource} />
        ) : (
          <TraceTab steps={trace} />
        )}
      </div>
    </aside>
  );
});

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 text-center py-3 px-4 text-[13px] font-medium transition-all duration-150 relative
        ${
          active
            ? 'text-amber-warm'
            : 'text-ink-muted hover:text-ink-light'
        }`}
    >
      {label}
      {count > 0 && (
        <span
          className={`ml-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded-full
            ${
              active
                ? 'bg-amber-warm/15 text-amber-warm'
                : 'bg-base-750 text-ink-dim'
            }`}
        >
          {count}
        </span>
      )}
      {active && (
        <span className="absolute bottom-0 left-4 right-4 h-0.5 bg-amber-warm rounded-full" />
      )}
    </button>
  );
}
