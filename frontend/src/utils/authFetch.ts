/**
 * Thin fetch wrapper that attaches the JWT Authorization header and
 * redirects to /login on 401 so every page handles session expiry
 * without repeating the check everywhere.
 */
export function authH(): Record<string, string> {
  return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }
}

export async function authFetch(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = {
    ...authH(),
    ...(init.headers as Record<string, string> | undefined ?? {}),
  }
  const res = await fetch(url, { ...init, headers })
  if (res.status === 401) {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    window.location.href = '/login'
  }
  return res
}
