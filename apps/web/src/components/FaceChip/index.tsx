import { useT } from '~/i18n'
import styles from './FaceChip.module.css'

interface Props {
  name?: string | null
  count?: number
  src?: string
  you?: boolean
  onClick?: () => void
}

/** Shell for M2 (people). Round corners are allowed here. */
export function FaceChip({ name, count, src, you, onClick }: Props) {
  const t = useT()
  const cls = [styles.chip, you ? styles.you : null, !name ? styles.unnamed : null]
    .filter(Boolean)
    .join(' ')
  return (
    <button type="button" className={cls} onClick={onClick}>
      {src ? <img className={styles.face} src={src} alt="" /> : <span className={styles.face} />}
      <span className={styles.name}>{you ? t('common.you') : (name ?? '—')}</span>
      {typeof count === 'number' ? (
        <span className={styles.count}>{t('common.photos', { count })}</span>
      ) : null}
    </button>
  )
}
