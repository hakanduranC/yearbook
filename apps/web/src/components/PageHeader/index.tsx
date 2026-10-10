import { Link, type LinkProps, useRouter } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useT } from '~/i18n'
import styles from './PageHeader.module.css'

interface Props {
  title: ReactNode
  /** Where the back arrow goes. `history` pops the stack. */
  back?: LinkProps['to'] | 'history' | null
  backParams?: LinkProps['params']
  right?: ReactNode
  display?: boolean
  center?: boolean
  plain?: boolean
}

function ArrowLeft() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M12.5 4 6.5 10l6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" />
    </svg>
  )
}

export function PageHeader({
  title,
  back = '/',
  backParams,
  right,
  display,
  center,
  plain,
}: Props) {
  const t = useT()
  const router = useRouter()
  const titleClass = [
    styles.title,
    display ? styles.titleDisplay : null,
    center ? styles.center : null,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <header className={[styles.header, plain ? styles.plain : null].filter(Boolean).join(' ')}>
      {back === 'history' ? (
        <button
          type="button"
          className={styles.back}
          onClick={() => router.history.back()}
          aria-label={t('nav.back')}
        >
          <ArrowLeft />
        </button>
      ) : back ? (
        <Link to={back} params={backParams} className={styles.back} aria-label={t('nav.back')}>
          <ArrowLeft />
        </Link>
      ) : (
        <span />
      )}
      <h1 className={titleClass}>{title}</h1>
      <div className={styles.right}>{right}</div>
    </header>
  )
}
