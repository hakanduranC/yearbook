import { intlTag, type Locale } from '~/i18n'

const dateCache = new Map<string, Intl.DateTimeFormat>()

function formatter(
  locale: Locale,
  options: Intl.DateTimeFormatOptions,
  timeZone?: string,
): Intl.DateTimeFormat {
  const key = `${locale}|${timeZone ?? ''}|${JSON.stringify(options)}`
  let f = dateCache.get(key)
  if (!f) {
    f = new Intl.DateTimeFormat(intlTag(locale), { ...options, timeZone })
    dateCache.set(key, f)
  }
  return f
}

/** "Sa., 14. Juni" / "Sat, 14 June" */
export function formatEventDate(iso: string, locale: Locale, timeZone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return formatter(locale, { weekday: 'short', day: 'numeric', month: 'long' }, timeZone).format(
    date,
  )
}

/** "Sa., 14. Juni" for the day of a group header. */
export function formatGroupDay(iso: string, locale: Locale, timeZone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return formatter(locale, { weekday: 'long', day: 'numeric', month: 'long' }, timeZone).format(
    date,
  )
}

/** "Sa. 23:14" */
export function formatTime(iso: string, locale: Locale, timeZone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return formatter(
    locale,
    { weekday: 'short', hour: '2-digit', minute: '2-digit' },
    timeZone,
  ).format(date)
}

/** "1:05" for a video badge. */
export function formatDuration(ms: number | null | undefined): string {
  if (!ms || ms < 0) return ''
  const total = Math.round(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/** Local datetime-local input value from an ISO string. */
export function toDateTimeLocal(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromDateTimeLocal(value: string): string {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '' : d.toISOString()
}

/** "14. Juni 2026" / "June 14, 2026" / "14 Haziran 2026" */
export function formatLongDate(iso: string, locale: Locale, timeZone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return formatter(locale, { day: 'numeric', month: 'long', year: 'numeric' }, timeZone).format(
    date,
  )
}

export function formatNumber(value: number, locale: Locale): string {
  return new Intl.NumberFormat(intlTag(locale)).format(value)
}
