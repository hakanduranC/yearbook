import type { ReactNode } from 'react'
import { useT } from '~/i18n'
import type { Album } from '~/lib/api/types'
import styles from './AlbumCard.module.css'

interface Props {
  album: Album
  actions?: ReactNode
  eventTitle?: string
}

export function AlbumCard({ album, actions, eventTitle }: Props) {
  const t = useT()
  return (
    <article className={styles.card} data-album={album.id}>
      <div className={styles.row}>
        {album.cover?.thumb ? (
          <img className={styles.cover} src={album.cover.small ?? album.cover.thumb} alt="" />
        ) : (
          <span className={styles.cover} />
        )}
        <div className={styles.text}>
          <span className="eyebrow">{t(`album.kind.${album.kind}`)}</span>
          <h3 className={styles.title}>{album.title}</h3>
          <span className={styles.meta}>
            {t('common.photos', { count: album.count })}
            {eventTitle ? ` · ${t('album.from', { title: eventTitle })}` : ''}
          </span>
        </div>
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </article>
  )
}
