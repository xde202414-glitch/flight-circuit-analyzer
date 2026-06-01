import { create } from 'zustand';

export type StatusSeverity = 'info' | 'success' | 'warning' | 'error';

export interface StatusMessage {
  id: number;
  severity: StatusSeverity;
  title: string;
  message: string;
  source?: string;
  timestamp: number;
}

interface StatusState {
  current: StatusMessage;
  history: StatusMessage[];
  setStatus: (message: Omit<StatusMessage, 'id' | 'timestamp'>) => void;
  clearHistory: () => void;
}

const initialStatus: StatusMessage = {
  id: 0,
  severity: 'info',
  title: '就绪',
  message: '请配置跑道、选择机型并生成目视飞行程序。',
  timestamp: Date.now(),
};

export const useStatusStore = create<StatusState>((set) => ({
  current: initialStatus,
  history: [initialStatus],
  setStatus: (message) =>
    set((state) => {
      const nextMessage: StatusMessage = {
        ...message,
        id: state.current.id + 1,
        timestamp: Date.now(),
      };

      return {
        current: nextMessage,
        history: [nextMessage, ...state.history].slice(0, 12),
      };
    }),
  clearHistory: () =>
    set((state) => ({
      history: [state.current],
    })),
}));
