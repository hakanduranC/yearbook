export type Locale = 'de' | 'en'

export type Plural = { one: string; other: string }

export type Entry = string | Plural

/** Builds the dictionary shape from the German source so English must match key for key. */
export type DictionaryOf<T extends Record<string, Entry>> = {
  [K in keyof T]: T[K] extends string ? string : Plural
}
