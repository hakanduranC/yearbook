import type { ReactNode } from 'react'
import { useT } from '~/i18n'
import styles from './EmptyState.module.css'

export type EmptyKind =
  | 'no-photos'
  | 'analyzing'
  | 'coming-soon'
  | 'offline'
  | 'mine'
  | 'not-found'
  | 'share'
  | 'no-people'
  | 'search'
  | 'no-year'
  | 'no-highlights'
  | 'library'

const copy: Record<
  EmptyKind,
  { title: Parameters<ReturnType<typeof useT>>[0]; body: Parameters<ReturnType<typeof useT>>[0] }
> = {
  'no-photos': { title: 'empty.noPhotos.title', body: 'empty.noPhotos.body' },
  analyzing: { title: 'empty.analyzing.title', body: 'empty.analyzing.body' },
  'coming-soon': { title: 'empty.comingSoon.title', body: 'empty.comingSoon.body' },
  offline: { title: 'empty.offline.title', body: 'empty.offline.body' },
  mine: { title: 'empty.mine.title', body: 'empty.mine.body' },
  'not-found': { title: 'empty.notFound.title', body: 'empty.notFound.body' },
  share: { title: 'empty.share.title', body: 'empty.share.body' },
  'no-people': { title: 'people.empty.title', body: 'people.empty.body' },
  search: { title: 'search.empty.title', body: 'search.tryThese' },
  'no-year': { title: 'year.empty.title', body: 'year.empty.body' },
  'no-highlights': { title: 'best.empty.title', body: 'best.empty.body' },
  library: { title: 'library.title', body: 'library.empty' },
}

export function EmptyState({
  kind,
  action,
  title,
  body,
}: {
  kind: EmptyKind
  action?: ReactNode
  title?: ReactNode
  body?: ReactNode
}) {
  const t = useT()
  return (
    <div
      className={[styles.empty, kind === 'analyzing' ? styles.analyzing : null]
        .filter(Boolean)
        .join(' ')}
      data-empty={kind}
    >
      <div className={styles.mark} aria-hidden="true" />
      <h2 className={styles.title}>{title ?? t(copy[kind].title)}</h2>
      <p className={styles.body}>{body ?? t(copy[kind].body)}</p>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  )
}
