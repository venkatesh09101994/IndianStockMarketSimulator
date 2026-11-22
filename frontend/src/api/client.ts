import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token && config.headers) {
    config.headers.Authorization = 'Bearer ' + token;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config as any;
    // A stale token should not lock the user out of the local no-login mode:
    // discard it, clear the session cookie, and retry the request once.
    if (error.response?.status === 401 && config && !config._retry && localStorage.getItem('auth_token')) {
      config._retry = true;
      localStorage.removeItem('auth_token');
      try {
        await api.post('/auth/logout');
      } catch {
        // Logout is best-effort; the retry below still drops the bad header.
      }
      if (config.headers) {
        delete config.headers.Authorization;
      }
      return api(config);
    }
    return Promise.reject(error);
  },
);

export default api;
