import { memo, useRef, useEffect } from 'react';
import type { Message, TraceStep } from '../types';
import MessageBubble from './MessageBubble';
import ThinkingSteps from './ThinkingSteps';
import TraceTab from './TraceTab';

interface ChatAreaProps {
  messages: Message[];
  isProcessing: boolean;
  activeTrace: TraceStep[] | null;
}

export default memo(function ChatArea({
  messages,
  isProcessing,
  activeTrace,
}: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return <WelcomeScreen />;
  }

  const lastMsg = messages[messages.length - 1];
  const isStreamingEmpty = isProcessing && lastMsg?.role === 'agent' && lastMsg.content.length === 0;

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin">
      <div className="max-w-3xl mx-auto px-6 py-6 flex flex-col gap-6">
        {messages.map((msg, idx) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isLast={idx === messages.length - 1}
            isStreaming={isProcessing && msg.role === 'agent' && idx === messages.length - 1}
          />
        ))}

        {isStreamingEmpty && <TypingIndicator />}

        {/* Inline context panel: trace below the last message */}
        {activeTrace && !isStreamingEmpty && (
          <div className="border-t border-surface-border pt-5 mt-2 space-y-5 animate-fade-in">
            {activeTrace.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-ink-muted uppercase tracking-wider mb-3">
                  推理过程
                </h3>
                <TraceTab steps={activeTrace} />
              </div>
            )}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
});

function WelcomeScreen() {
  return (
    <div className="flex-1 flex items-center justify-center px-8">
      <div className="text-center max-w-md animate-fade-in">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center shadow-lg shadow-primary-200">
          <span className="text-white font-mono text-2xl font-medium">R</span>
        </div>
        <h2 className="font-display text-2xl text-ink-strong font-medium mb-3 tracking-tight">
          RAG Agent
        </h2>
        <p className="text-ink-muted text-sm leading-relaxed">
          基于检索增强生成的智能助手。连接了你的知识库，
          <br />
          每次回答都会展示推理过程和引用来源。
        </p>
        <p className="text-ink-dim text-xs mt-4">
          试着在下方输入你的第一个问题
        </p>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-4 py-1 animate-fade-in">
      <div className="flex gap-1.5">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-primary-400 animate-bounce-dot"
            style={{ animationDelay: `${i * 0.2}s` }}
          />
        ))}
      </div>
      <span className="text-xs text-ink-muted italic">Agent 正在处理…</span>
    </div>
  );
}
