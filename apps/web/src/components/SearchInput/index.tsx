import { type FormEvent, useId } from 'react'
import { useT } from '~/i18n'
import styles from './SearchInput.module.css'

interface Props {
  value?: string
  onChange?: (value: string) => void
  onSubmit?: (value: string) => void
  busy?: boolean
  disabled?: boolean
  /** Sits in the page flow instead of floating above the bottom bar. */
  inline?: boolean
  autoFocus?: boolean
  placeholder?: string
}

/** The "Ask for anything" input. Floating by default; Enter submits. */
export function SearchInput({
  value = '',
  onChange,
  onSubmit,
  busy,
  disabled = false,
  inline,
  autoFocus,
  placeholder,
}: Props) {
  const t = useT()
  const id = useId()
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    const text = value.trim()
    if (!text || disabled || busy) return
    onSubmit?.(text)
  }
  return (
    <form
      className={[styles.wrap, inline ? styles.inline : null, 'no-print'].filter(Boolean).join(' ')}
      onSubmit={submit}
      aria-label={t('photos.ask')}
      data-ask
    >
      <input
        id={id}
        className={styles.input}
        type="search"
        enterKeyHint="search"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="sentences"
        placeholder={placeholder ?? t('photos.ask')}
        disabled={disabled}
        value={value}
        onChange={(ev) => onChange?.(ev.target.value)}
        // biome-ignore lint/a11y/noAutofocus: the search page exists to type into
        autoFocus={autoFocus}
      />
      <button
        type="submit"
        className={styles.go}
        disabled={disabled || busy || !value.trim()}
        aria-label={t('photos.ask')}
        aria-busy={busy || undefined}
      >
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M4 10h11M10 5l5 5-5 5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="square"
          />
        </svg>
      </button>
    </form>
  )
}
