import { Link, type LinkProps } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useT } from '~/i18n'
import styles from './FaceChip.module.css'

interface Props {
  name?: string | null
  count?: number
  /** Label under the name instead of the photo count. */
  caption?: ReactNode
  src?: string
  you?: boolean
  selected?: boolean
  size?: 'md' | 'lg'
  onClick?: () => void
  link?: Pick<LinkProps, 'to' | 'params' | 'search'>
  'data-person'?: string
}

/** A face with a name. Gold ring when the person is you, dashed when unnamed. Round corners are allowed here. */
export function FaceChip({
  name,
  count,
  caption,
  src,
  you,
  selected,
  size = 'md',
  onClick,
  link,
  ...data
}: Props) {
  const t = useT()
  const unnamed = !name && !you
  const cls = [
    styles.chip,
    you ? styles.you : null,
    unnamed ? styles.unnamed : null,
    selected ? styles.selected : null,
    size === 'lg' ? styles.lg : null,
  ]
    .filter(Boolean)
    .join(' ')
  const body = (
    <>
      {src ? (
        <img className={styles.face} src={src} alt="" loading="lazy" />
      ) : (
        <span className={styles.face} />
      )}
      <span className={styles.name}>{you ? t('common.you') : (name ?? t('people.unknown'))}</span>
      {caption !== undefined ? (
        <span className={styles.count}>{caption}</span>
      ) : typeof count === 'number' ? (
        <span className={styles.count}>{t('common.photos', { count })}</span>
      ) : null}
    </>
  )
  if (link) {
    return (
      <Link {...link} className={cls} {...data}>
        {body}
      </Link>
    )
  }
  return (
    <button
      type="button"
      className={cls}
      onClick={onClick}
      aria-pressed={selected === undefined ? undefined : selected}
      {...data}
    >
      {body}
    </button>
  )
}
