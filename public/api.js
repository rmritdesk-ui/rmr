export class ApiError extends Error {
  constructor(message, {status=0, fieldErrors={}, data=null} = {}) {
    super(message || 'Request failed');
    this.name = 'ApiError';
    this.status = status;
    this.fieldErrors = fieldErrors || {};
    this.data = data;
  }
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData) && options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }
  if (options.method && options.method !== 'GET') headers.set('X-RMR-Request', '1');
  const managedSession = sessionStorage.getItem('rmr_managed_session');
  if (managedSession) headers.set('X-RMR-Managed-Session', managedSession);
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers,
    body: options.body instanceof FormData ? options.body : options.body !== undefined ? JSON.stringify(options.body) : undefined
  });
  if (response.status === 401) window.dispatchEvent(new CustomEvent('rmr:unauthorized'));
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof data === 'object' ? data.detail ?? data.message : data;
    if (detail && typeof detail === 'object') {
      throw new ApiError(detail.message || data.message || `Request failed (${response.status})`, {
        status: response.status,
        fieldErrors: detail.field_errors || {},
        data: detail
      });
    }
    throw new ApiError(detail || `Request failed (${response.status})`, {status: response.status, data});
  }
  return data;
}
