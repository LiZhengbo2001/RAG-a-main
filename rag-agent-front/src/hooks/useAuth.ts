import { useState, useCallback, useEffect } from 'react';
import type { UserInfo } from '../api/client';
import { login as apiLogin, register as apiRegister, getMe } from '../api/client';

const TOKEN_KEY = 'rag_agent_token';

export interface UseAuthReturn {
  user: UserInfo | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export function useAuth(): UseAuthReturn {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [loading, setLoading] = useState(true);

  // 已有 token 时自动拉取用户信息
  useEffect(() => {
    if (!token) { setLoading(false); return; }
    getMe().then(setUser).catch(() => { localStorage.removeItem(TOKEN_KEY); setToken(null); }).finally(() => setLoading(false));
  }, [token]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    localStorage.setItem(TOKEN_KEY, res.access_token);
    setToken(res.access_token);
    const me = await getMe();
    setUser(me);
  }, []);

  const register = useCallback(async (username: string, password: string) => {
    const res = await apiRegister(username, password);
    localStorage.setItem(TOKEN_KEY, res.access_token);
    setToken(res.access_token);
    const me = await getMe();
    setUser(me);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  return { user, token, loading, login, register, logout };
}