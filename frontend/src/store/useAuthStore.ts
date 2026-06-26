import { create } from 'zustand';
import axios from 'axios';

interface User {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
  checkAuth: () => void;
}

const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';

function readStoredToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

function readStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export const useAuthStore = create<AuthState>((set) => ({
  user: readStoredUser(),
  token: readStoredToken(),
  isAuthenticated: !!readStoredToken(),
  isLoading: false,

  login: async (username: string, password: string) => {
    set({ isLoading: true });
    try {
      const res = await axios.post('/api/v1/auth/login', { username, password });
      const { access_token, user } = res.data;
      localStorage.setItem(TOKEN_KEY, access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      set({ user, token: access_token, isAuthenticated: true, isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      const msg = e?.response?.data?.detail || '登录失败';
      throw new Error(msg);
    }
  },

  register: async (username: string, password: string) => {
    set({ isLoading: true });
    try {
      const res = await axios.post('/api/v1/auth/register', { username, password });
      const { access_token, user } = res.data;
      localStorage.setItem(TOKEN_KEY, access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      set({ user, token: access_token, isAuthenticated: true, isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      const msg = e?.response?.data?.detail || '注册失败';
      throw new Error(msg);
    }
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({ user: null, token: null, isAuthenticated: false });
  },

  checkAuth: () => {
    const token = readStoredToken();
    const user = readStoredUser();
    set({ token, user, isAuthenticated: !!token && !!user });
  },
}));
