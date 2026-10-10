import { describe, expect, it } from 'vitest'
import { de, en, intlTag, resolveLocale, t, tr } from '~/i18n'

const emoji = /\p{Extended_Pictographic}/u
const keys = Object.keys(de) as Array<keyof typeof de>

function forms(entry: string | { one: string; other: string }): string[] {
  return typeof entry === 'string' ? [entry] : [entry.one, entry.other]
}

describe('dictionaries', () => {
  it('have the same keys in all three languages', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(de).sort())
    expect(Object.keys(tr).sort()).toEqual(Object.keys(de).sort())
  })

  it('have the same entry shape per key', () => {
    for (const key of keys) {
      expect(typeof en[key], key).toBe(typeof de[key])
      expect(typeof tr[key], key).toBe(typeof de[key])
    }
  })

  it('contain no emoji', () => {
    for (const dict of [de, en, tr]) {
      for (const key of keys) {
        for (const form of forms(dict[key])) expect(form, `${key}: ${form}`).not.toMatch(emoji)
      }
    }
  })

  it('use sentence case (no Title Case Headings)', () => {
    const titleCase = /^(?:[A-ZÄÖÜİŞÇĞ][a-zäöüßıişçğ]+ ){2,}[A-ZÄÖÜİŞÇĞ][a-zäöüßıişçğ]+$/
    for (const dict of [de, en, tr]) {
      for (const key of keys) {
        for (const form of forms(dict[key])) expect(form, `${key}: ${form}`).not.toMatch(titleCase)
      }
    }
  })

  it('address the reader as du / you / sen, never Sie or siz', () => {
    for (const key of keys) {
      for (const form of forms(de[key])) expect(form, key).not.toMatch(/\bSie\b|\bIhr(e|en|em)?\b/)
      for (const form of forms(tr[key]))
        expect(form, key).not.toMatch(/\bsiz\b|\bsizin\b|\bsize\b|(?:ebilir|malı|melı)siniz\b/i)
    }
  })

  it('use the same placeholders in all languages', () => {
    for (const key of keys) {
      const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
      const a = forms(de[key]).flatMap(placeholders).sort()
      for (const dict of [en, tr]) {
        const b = forms(dict[key]).flatMap(placeholders).sort()
        expect(new Set(b), key).toEqual(new Set(a))
      }
    }
  })
})

describe('t', () => {
  it('interpolates', () => {
    expect(t('en', 'landing.invites', { name: 'Mert' })).toBe('Mert invites you to')
    expect(t('de', 'landing.invites', { name: 'Mert' })).toBe('Mert lädt dich ein zu')
  })

  it('pluralizes with Intl.PluralRules', () => {
    expect(t('en', 'common.photos', { count: 1 })).toBe('1 photo')
    expect(t('en', 'common.photos', { count: 0 })).toBe('0 photos')
    expect(t('de', 'upload.resume', { count: 1 })).toBe('1 Upload fortsetzen')
    expect(t('de', 'upload.resume', { count: 3 })).toBe('3 Uploads fortsetzen')
  })

  it('leaves unknown placeholders alone', () => {
    expect(t('en', 'login.sentBody', {})).toContain('{email}')
  })

  it('translates Turkish and formats it as tr-TR', () => {
    expect(t('tr', 'landing.add')).toBe('Fotoğraflarını ekle')
    expect(t('tr', 'common.photos', { count: 3 })).toBe('3 fotoğraf')
    expect(intlTag('tr')).toBe('tr-TR')
    expect(intlTag('de')).toBe('de')
    expect(
      new Intl.DateTimeFormat(intlTag('tr'), { month: 'long', timeZone: 'UTC' }).format(
        new Date('2026-06-14T00:00:00Z'),
      ),
    ).toBe('Haziran')
  })
})

describe('resolveLocale', () => {
  it('prefers the yb_lang cookie', () => {
    expect(resolveLocale('a=b; yb_lang=en', 'de-DE')).toBe('en')
  })
  it('falls back to Accept-Language by quality', () => {
    expect(resolveLocale(null, 'fr-FR, en;q=0.8, de;q=0.9')).toBe('de')
    expect(resolveLocale(null, 'en-US,en;q=0.9')).toBe('en')
  })
  it('detects Turkish browsers', () => {
    expect(resolveLocale(null, 'tr-TR,tr;q=0.9,en;q=0.8')).toBe('tr')
    expect(resolveLocale('yb_lang=tr', 'de')).toBe('tr')
  })
  it('defaults to German', () => {
    expect(resolveLocale(null, 'fr')).toBe('de')
    expect(resolveLocale(undefined, undefined)).toBe('de')
  })
})
