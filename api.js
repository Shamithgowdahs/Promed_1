(function () {
  const apiBase = window.PROMED_API_BASE_URL || 'http://127.0.0.1:8000/api';

  async function request(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers
      }
    });

    if (response.status === 204) return null;

    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error(`The API returned an invalid JSON response: ${error.message}`);
    }
    if (!response.ok) {
      const detail = payload && payload.detail;
      const message = Array.isArray(detail)
        ? detail.map(issue => `${issue.loc.slice(1).join('.')}: ${issue.msg}`).join('; ')
        : detail || `Request failed (${response.status})`;
      throw new Error(message);
    }
    return payload;
  }

  window.PromedApi = Object.freeze({
    get: path => request(path),
    post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) }),
    put: (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body) }),
    patch: (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) }),
    upload: (path, file) => request(path, {
      method: 'POST',
      body: file,
      headers: { 'Content-Type': file.type }
    }),
    delete: path => request(path, { method: 'DELETE' })
  });
})();
