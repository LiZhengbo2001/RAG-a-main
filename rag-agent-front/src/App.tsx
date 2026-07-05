import { useState, useEffect } from 'react';
import type { NavTab } from './types';
import { useAuth } from './hooks/useAuth';
import { useChat } from './hooks/useChat';
import { useKnowledge } from './hooks/useKnowledge';
import Header from './components/Header';
import ChatArea from './components/ChatArea';
import ChatInput from './components/ChatInput';
import ConversationPanel from './components/ConversationPanel';
import KnowledgeBase from './components/KnowledgeBase';
import LoginPage from './components/LoginPage';
import ProtectedRoute from './components/ProtectedRoute';

export default function App() {
  const auth = useAuth();
  const [activeTab, setActiveTab] = useState<NavTab>('chat');

  const chat = useChat(auth.token);
  const knowledge = useKnowledge(auth.token);

  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '1') { e.preventDefault(); setActiveTab('chat'); }
      if ((e.ctrlKey || e.metaKey) && e.key === '2') { e.preventDefault(); setActiveTab('knowledge'); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <ProtectedRoute
      token={auth.token}
      loading={auth.loading}
      loginSlot={
        <LoginPage
          onLogin={auth.login}
          onRegister={auth.register}
          error={authError}
        />
      }
    >
      <div className="flex flex-col h-screen bg-surface-muted text-ink-body">
        <Header
          activeTab={activeTab}
          onTabChange={setActiveTab}
          username={auth.user?.username ?? null}
          onLogout={auth.logout}
        />

        <main className="flex-1 flex overflow-hidden">
          {activeTab === 'chat' ? (
            <>
              <ConversationPanel
                conversations={chat.conversations}
                activeId={chat.conversationId}
                onNew={chat.newConversation}
                onSwitch={chat.switchConversation}
                onDelete={chat.removeConversation}
              />

              <div className="flex-1 flex flex-col min-w-0">
                <ChatArea
                  messages={chat.messages}
                  isProcessing={chat.isProcessing}
                  activeTrace={chat.activeTrace}
                />
                <ChatInput
                  onSend={chat.send}
                  onAbort={chat.abort}
                  isProcessing={chat.isProcessing}
                />
              </div>
            </>
          ) : (
            <KnowledgeBase {...knowledge} />
          )}
        </main>

        {(chat.error || knowledge.error) && (
          <div className="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 animate-fade-up">
            <div className="bg-red-50 border border-red-200 text-red-700 px-5 py-3 rounded-xl text-sm shadow-lg backdrop-blur-sm flex items-center gap-3 max-w-lg">
              <span className="flex-1">{toUserMessage(chat.error || knowledge.error || '')}</span>
              <button
                onClick={() => { /* Auto-dismiss handled by hook */ }}
                className="text-red-400 hover:text-red-600 transition-colors text-lg leading-none"
              >
                ×
              </button>
            </div>
          </div>
        )}
      </div>
    </ProtectedRoute>
  );
}

/** 将后端错误信息转换为用户可读的中文提示 */
function toUserMessage(raw: string): string {
  const map: Record<string, string> = {
    '文件内容为空': '文件内容为空，请选择有效文件',
    '文件名为空': '文件名为空，请选择有效文件',
    '用户名已存在': '该用户名已被注册，请换一个',
    '用户名或密码错误': '用户名或密码错误',
    'Token 无效或已过期': '登录已过期，请重新登录',
    'Token 无效': '登录已过期，请重新登录',
    '用户不存在': '账号不存在',
    '对话不存在': '该对话已被删除或不存在',
    '文档不存在': '该文档已被删除或不存在',
    '无权访问此对话': '无权访问此对话',
    '无权删除此对话': '无权删除此对话',
    '无权删除此文档': '无权删除此文档',
    '登录已过期，请重新登录': '登录已过期，请重新登录',
    '加载对话历史失败': '加载历史消息失败',
    '请求失败': '网络异常，请稍后重试',
  };

  for (const [key, val] of Object.entries(map)) {
    if (raw.includes(key)) return val;
  }

  // fallback: 去掉技术性前缀
  return raw.length > 80 ? '操作失败，请稍后重试' : raw;
}
