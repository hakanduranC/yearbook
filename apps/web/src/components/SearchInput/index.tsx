import { useT } from '~/i18n'
import styles from './SearchInput.module.css'

/** Shell for the agent input. Disabled until search lands (M3). */
export function SearchInput({ disabled = true }: { disabled?: boolean }) {
  const t = useT()
  return (
    <form
      className={[styles.wrap, 'no-print'].join(' ')}
      onSubmit={(ev) => ev.preventDefault()}
      aria-label={t('photos.ask')}
      title={disabled ? t('photos.askSoon') : undefined}
    >
      <input
        className={styles.input}
        type="search"
        placeholder={t('photos.ask')}
        disabled={disabled}
      />
      <button type="submit" className={styles.go} disabled={disabled} aria-label={t('photos.ask')}>
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
