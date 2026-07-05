import { memo } from 'react';
import type { NavTab } from '../types';

interface HeaderProps {
  activeTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  username: string | null;
  onLogout: () => void;
}

export default memo(function Header({ activeTab, onTabChange, username, onLogout }: HeaderProps) {
  return (
    <header className="flex items-center justify-between px-6 py-3 bg-white border-b border-surface-border shadow-sm flex-shrink-0">
      <div className="flex items-center gap-4">
        {/* Logo */}
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center text-white font-mono text-sm font-medium select-none shadow-sm shadow-primary-200">
          R
        </div>
        <h1 className="font-display text-lg font-medium text-ink-strong tracking-tight">
          RAG <span className="text-primary-600 font-semibold">Agent</span>
        </h1>
      </div>

      {/* Nav tabs */}
      <nav className="flex bg-surface-raised rounded-xl p-1 gap-0.5">
        <TabButton
          active={activeTab === 'chat'}
          onClick={() => onTabChange('chat')}
          shortcut="1"
        >
          对话
        </TabButton>
        <TabButton
          active={activeTab === 'knowledge'}
          onClick={() => onTabChange('knowledge')}
          shortcut="2"
        >
          知识库
        </TabButton>
      </nav>

      {/* User area */}
      <div className="flex items-center gap-3 min-w-[100px] justify-end">
        {username && (
          <>
            <span className="text-xs text-ink-muted">{username}</span>
            <button
              onClick={onLogout}
              className="text-xs text-ink-dim hover:text-red-500 transition-colors"
            >
              退出
            </button>
          </>
        )}
      </div>
    </header>
  );
});

function TabButton({
  active,
  onClick,
  children,
  shortcut,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
  shortcut: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative px-4 py-2 rounded-[10px] text-sm font-medium transition-all duration-200
        ${active
          ? 'bg-white text-primary-600 shadow-sm shadow-black/5'
          : 'text-ink-muted hover:text-ink-body hover:bg-white/50'
        }`}
    >
      {children}
      <span className={`ml-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded-md
        ${active ? 'bg-primary-50 text-primary-500' : 'bg-surface-border text-ink-dim'}`}>
        ⌘{shortcut}
      </span>
    </button>
  );
}
