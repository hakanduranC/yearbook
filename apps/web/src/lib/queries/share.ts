export function qrUrl(slug: string): string {
  return `/api/v1/events/${encodeURIComponent(slug)}/qr.svg`
}

export function eventUrl(origin: string, slug: string): string {
  return `${origin}/e/${encodeURIComponent(slug)}`
}
