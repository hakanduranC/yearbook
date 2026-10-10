/** Public origin of the web app, for absolute URLs in OG tags and QR links. */
export function publicOrigin(): string {
  if (import.meta.env.SSR) return process.env.PUBLIC_WEB_ORIGIN ?? 'http://localhost:3000'
  return window.location.origin
}

export function readLangCookie(): string | undefined {
  if (typeof document === 'undefined') return undefined
  return document.cookie.match(/(?:^|;\s*)yb_lang=([a-zA-Z-]+)/)?.[1]
}

export function writeLangCookie(locale: string) {
  // biome-ignore lint/suspicious/noDocumentCookie: cookieStore is not available in Safari
  document.cookie = `yb_lang=${locale}; path=/; max-age=31536000; samesite=lax`
}
