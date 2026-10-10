import { createContext, useContext } from 'react'
import { de } from './de'
import { en } from './en'
import type { Entry, Locale, Plural } from './types'

export type { Locale } from './types'

export type Key = keyof typeof de
export type Params = Record<string, string | number>

export const locales: readonly Locale[] = ['de', 'en']
export const defaultLocale: Locale = 'de'

const dictionaries: Record<Locale, Record<Key, Entry>> = { de, en }

const pluralRules = new Map<Locale, Intl.PluralRules>()
function rules(locale: Locale): Intl.PluralRules {
  let r = pluralRules.get(locale)
  if (!r) {
    r = new Intl.PluralRules(locale)
    pluralRules.set(locale, r)
  }
  return r
}

function interpolate(template: string, params?: Params): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name]
    return value === undefined ? match : String(value)
  })
}

function pick(entry: Entry, locale: Locale, params?: Params): string {
  if (typeof entry === 'string') return entry
  const count = Number(params?.count ?? 0)
  const category = rules(locale).select(count)
  const form = (entry as Plural)[category === 'one' ? 'one' : 'other']
  return form
}

/** Translate `key` in `locale`. Plural entries pick a form from `params.count`; `{name}` placeholders interpolate. */
export function t(locale: Locale, key: Key, params?: Params): string {
  const entry = dictionaries[locale][key] ?? dictionaries[defaultLocale][key]
  return interpolate(pick(entry, locale, params), params)
}

export function isLocale(value: unknown): value is Locale {
  return value === 'de' || value === 'en'
}

/** Picks a locale from the yb_lang cookie, then Accept-Language, then German. */
export function resolveLocale(
  cookieHeader?: string | null,
  acceptLanguage?: string | null,
): Locale {
  const fromCookie = cookieHeader
    ?.match(/(?:^|;\s*)yb_lang=([a-zA-Z-]+)/)?.[1]
    ?.slice(0, 2)
    .toLowerCase()
  if (isLocale(fromCookie)) return fromCookie
  if (acceptLanguage) {
    const ranked = acceptLanguage
      .split(',')
      .map((part, index) => {
        const [tag = '', ...rest] = part.trim().split(';')
        const q = rest.find((p) => p.trim().startsWith('q='))
        return { tag: tag.toLowerCase(), q: q ? Number(q.trim().slice(2)) : 1, index }
      })
      .sort((a, b) => b.q - a.q || a.index - b.index)
    for (const { tag } of ranked) {
      const base = tag.slice(0, 2)
      if (isLocale(base)) return base
    }
  }
  return defaultLocale
}

export const LocaleContext = createContext<Locale>(defaultLocale)

export function useLocale(): Locale {
  return useContext(LocaleContext)
}

export type Translate = (key: Key, params?: Params) => string

export function useT(): Translate {
  const locale = useLocale()
  return (key, params) => t(locale, key, params)
}

export { de, en }
