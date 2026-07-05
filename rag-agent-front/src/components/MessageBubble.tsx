import { memo, useMemo } from 'react';
import type { Message, AgentMessage } from '../types';
import ThinkingSteps from './ThinkingSteps';
import RetrievalDetail from './RetrievalDetail';

interface MessageBubbleProps {
  message: Message;
  isLast: boolean;
  isStreaming: boolean;
}

export default memo(function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  if (message.role === 'user') {
    return <UserBubble content={message.content} timestamp={message.timestamp} />;
  }
  return <AgentBubble message={message} isStreaming={isStreaming} />;
});

function UserBubble({ content, timestamp }: { content: string; timestamp: string }) {
  return (
    <div className="flex justify-end animate-fade-up">
      <div className="max-w-[70%]">
        <div className="flex items-center gap-2 justify-end mb-1.5 px-1">
          <span className="text-[11px] text-ink-dim">{timestamp}</span>
          <span className="text-[11px] text-ink-dim font-medium uppercase tracking-wider">你</span>
        </div>
        <div className="bg-primary-600 text-white rounded-2xl rounded-br-md px-5 py-3.5 text-[15px] leading-relaxed">
          {content}
        </div>
      </div>
    </div>
  );
}

function AgentBubble({ message, isStreaming }: {
  message: AgentMessage;
  isStreaming: boolean;
}) {
  const { content, thinking, sources, timestamp } = message;
  const hasContent = content.length > 0;

  const formattedHtml = useMemo(() => formatContent(content), [content]);

  return (
    <div className="animate-fade-up">
      <div className="flex items-center gap-2 mb-2 px-1">
        <span className="font-display text-xs font-medium text-primary-600 tracking-wide">Agent</span>
        <span className="text-[11px] text-ink-dim">{timestamp}</span>
      </div>

      {thinking && thinking.length > 0 && (
        <div className="mb-4">
          <ThinkingSteps steps={thinking} defaultOpen={isStreaming} />
        </div>
      )}

      {/* 检索详情：展示每条命中文档的分数 */}
      {sources && sources.length > 0 && !isStreaming && (
        <RetrievalDetail sources={sources} />
      )}

      {hasContent && (
        <div className="text-[15px] leading-relaxed text-ink-body space-y-3.5">
          <div dangerouslySetInnerHTML={{ __html: formattedHtml }} />
        </div>
      )}

      {isStreaming && hasContent && (
        <span className="inline-block w-0.5 h-5 bg-primary-500 ml-0.5 animate-pulse-soft align-text-bottom" />
      )}
    </div>
  );
}

function formatContent(text: string): string {
  let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-ink-strong">$1</strong>');
  html = html.replace(/`([^`]+)`/g,
    '<code class="font-mono text-[0.9em] bg-primary-50 text-primary-700 px-1.5 py-0.5 rounded">$1</code>');
  html = html.replace(/\[([\d,\s]+)\]/g, (_m, nums: string) => {
    return nums.split(',').map((s: string) => s.trim()).filter(Boolean)
      .map((id: string) =>
        `<sup class="citation cursor-pointer font-semibold text-[0.78em] mx-px text-primary-500 hover:text-primary-700 transition-colors">[${id}]</sup>`)
      .join('');
  });
  return html.split('\n\n').map(p => p.trim()).filter(Boolean)
    .map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
}
