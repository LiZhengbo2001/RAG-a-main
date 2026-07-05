import { memo } from 'react';
import type { Conversation } from '../types';

interface ConversationPanelProps {
  conversations: Conversation[];
  activeId: string | null;
  onNew: () => void;
  onSwitch: (id: string) => void;
  onDelete: (id: string) => void;
}

export default memo(function ConversationPanel({
  conversations,
  activeId,
  onNew,
  onSwitch,
  onDelete,
}: ConversationPanelProps) {
  return (
    <aside className="w-[280px] border-r border-surface-border bg-white flex flex-col flex-shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
        <h2 className="text-sm font-semibold text-ink-strong">对话列表</h2>
        <button
          onClick={onNew}
          className="w-8 h-8 rounded-lg bg-primary-50 text-primary-600 hover:bg-primary-100
                     flex items-center justify-center transition-colors"
          title="新建对话"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {conversations.length === 0 ? (
          <div className="p-6 text-center">
            <p className="text-xs text-ink-muted leading-relaxed">
              暂无对话记录，
              <br />
              点击上方按钮新建对话。
            </p>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {conversations.map(c => (
              <div
                key={c.id}
                onClick={() => onSwitch(c.id)}
                className={`group flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-150
                  ${c.id === activeId
                    ? 'bg-primary-50 border border-primary-100'
                    : 'hover:bg-surface-muted border border-transparent'
                  }`}
              >
                <div className="flex-1 min-w-0">
                  <p className={`text-sm truncate ${c.id === activeId ? 'text-primary-700 font-medium' : 'text-ink-body'}`}>
                    {c.title}
                  </p>
                  <p className="text-[11px] text-ink-dim mt-0.5">
                    {formatDate(c.updated_at)}
                  </p>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); onDelete(c.id); }}
                  className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded-md flex items-center justify-center
                             text-ink-dim hover:text-red-500 hover:bg-red-50 transition-all duration-150"
                  title="删除对话"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-surface-border">
        <p className="text-[11px] text-ink-dim text-center">
          {conversations.length} 个对话
        </p>
      </div>
    </aside>
  );
});

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}
