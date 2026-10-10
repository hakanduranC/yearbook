import { Button } from '~/components/Button'
import { useLocale, useT } from '~/i18n'
import type { Suggestion } from '~/lib/api/types'
import { formatEventDate } from '~/lib/format'
import styles from './SuggestionCard.module.css'

interface Props {
  suggestion: Suggestion
  busy?: boolean
  onConfirm: () => void
  onDismiss: () => void
}

/** "Also you, at <event>?" with the crop; the confidence stays hidden on purpose. */
export function SuggestionCard({ suggestion, busy, onConfirm, onDismiss }: Props) {
  const t = useT()
  const locale = useLocale()
  const { person } = suggestion
  return (
    <article className={styles.card} data-suggestion={person.id}>
      {person.crop_url ? (
        <img className={styles.crop} src={person.crop_url} alt="" />
      ) : (
        <span className={styles.crop} />
      )}
      <div className={styles.text}>
        <h3 className={styles.title}>{t('suggest.title', { event: suggestion.event_title })}</h3>
        <span className={styles.meta}>
          {suggestion.event_starts_at ? formatEventDate(suggestion.event_starts_at, locale) : ''}
          {person.face_count ? ` · ${t('people.faces', { count: person.face_count })}` : ''}
        </span>
        <div className={styles.actions}>
          <Button small busy={busy} onClick={onConfirm} data-confirm-suggestion>
            {t('suggest.confirm')}
          </Button>
          <Button small variant="quiet" disabled={busy} onClick={onDismiss} data-dismiss-suggestion>
            {t('suggest.dismiss')}
          </Button>
        </div>
      </div>
    </article>
  )
}
