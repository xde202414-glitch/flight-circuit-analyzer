import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../store/useAuthStore';

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const { login, register, isLoading } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码');
      return;
    }
    try {
      if (mode === 'login') {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), password);
      }
      navigate('/');
    } catch (err: any) {
      setError(err.message || '操作失败');
    }
  };

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100vh', background: '#0f172a',
    }}>
      <div style={{
        background: '#1e293b', borderRadius: 12, padding: 40,
        width: 380, maxWidth: '90vw',
        boxShadow: '0 25px 50px rgba(0,0,0,0.4)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>✈</div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: '#f1f5f9', margin: 0 }}>
            飞行程序分析系统
          </h1>
          <p style={{ fontSize: 13, color: '#94a3b8', marginTop: 6 }}>
            {mode === 'login' ? '请登录以继续' : '注册新账户'}
          </p>
        </div>

        {error && (
          <div style={{
            background: '#fef2f2', color: '#991b1b', padding: '8px 12px',
            borderRadius: 6, fontSize: 13, marginBottom: 16,
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" style={{ color: '#cbd5e1' }}>用户名</label>
            <input
              className="form-input"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="输入用户名"
              autoFocus
              style={{ background: '#334155', border: '1px solid #475569', color: '#f1f5f9' }}
            />
          </div>
          <div className="form-group">
            <label className="form-label" style={{ color: '#cbd5e1' }}>密码</label>
            <input
              className="form-input"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="输入密码"
              style={{ background: '#334155', border: '1px solid #475569', color: '#f1f5f9' }}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={isLoading}
            style={{ width: '100%', marginTop: 8, padding: '10px 0', fontSize: 14 }}
          >
            {isLoading ? '处理中...' : mode === 'login' ? '登录' : '注册'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 20 }}>
          <button
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}
            style={{
              background: 'none', border: 'none', color: '#60a5fa',
              cursor: 'pointer', fontSize: 13,
            }}
          >
            {mode === 'login' ? '没有账户？注册' : '已有账户？登录'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
