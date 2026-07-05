import { memo, useState, useCallback } from 'react';

interface LoginPageProps {
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (username: string, password: string) => Promise<void>;
  error?: string | null;
}

export default memo(function LoginPage({ onLogin, onRegister, error }: LoginPageProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setLoading(true);
    setLocalError(null);
    try {
      if (isRegister) {
        await onRegister(username.trim(), password);
      } else {
        await onLogin(username.trim(), password);
      }
    } catch (err: any) {
      setLocalError(err.message || '操作失败');
    } finally {
      setLoading(false);
    }
  }, [username, password, isRegister, onLogin, onRegister]);

  const displayError = localError || error;

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface-muted">
      <div className="w-full max-w-sm">
        <div className="bg-white rounded-2xl shadow-sm border border-surface-border px-8 py-10">
          {/* Logo */}
          <div className="w-14 h-14 mx-auto mb-5 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center shadow-sm shadow-primary-200">
            <span className="text-white font-mono text-xl font-medium">R</span>
          </div>

          <h1 className="font-display text-xl text-ink-strong font-medium text-center mb-1 tracking-tight">
            RAG <span className="text-primary-600 font-semibold">Agent</span>
          </h1>
          <p className="text-sm text-ink-muted text-center mb-7">
            {isRegister ? '创建账号以开始使用' : '登录以继续'}
          </p>

          {/* Error */}
          {displayError && (
            <div className="mb-5 px-4 py-2.5 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600 text-center">
              {displayError}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="text"
                placeholder="用户名"
                value={username}
                onChange={e => setUsername(e.target.value)}
                disabled={loading}
                className="w-full px-4 py-3 bg-surface-muted border border-surface-border rounded-xl text-sm text-ink-strong placeholder:text-ink-dim outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-50 transition-all disabled:opacity-50"
                autoComplete="username"
              />
            </div>
            <div>
              <input
                type="password"
                placeholder="密码"
                value={password}
                onChange={e => setPassword(e.target.value)}
                disabled={loading}
                className="w-full px-4 py-3 bg-surface-muted border border-surface-border rounded-xl text-sm text-ink-strong placeholder:text-ink-dim outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-50 transition-all disabled:opacity-50"
                autoComplete={isRegister ? 'new-password' : 'current-password'}
              />
            </div>

            <button
              type="submit"
              disabled={loading || !username.trim() || !password.trim()}
              className="w-full py-3 bg-primary-500 text-white rounded-xl text-sm font-medium hover:bg-primary-600 active:scale-[0.98] transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm shadow-primary-200"
            >
              {loading ? '处理中…' : isRegister ? '注册' : '登录'}
            </button>
          </form>

          <p className="text-center mt-5 text-xs text-ink-muted">
            {isRegister ? '已有账号？' : '没有账号？'}
            <button
              onClick={() => { setIsRegister(!isRegister); setLocalError(null); }}
              className="ml-1 text-primary-500 hover:text-primary-700 font-medium transition-colors"
              disabled={loading}
            >
              {isRegister ? '去登录' : '去注册'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
});
