import { Button } from '~/components/Button'
import { useT } from '~/i18n'
import { bytesSent, percentOf } from '~/lib/upload/machine'
import type { UploadItemState } from '~/lib/upload/types'
import styles from './UploadList.module.css'

interface ItemProps {
  item: UploadItemState
  onRetry: (id: string) => void
  onCancel: (id: string) => void
}

export function UploadItem({ item, onRetry, onCancel }: ItemProps) {
  const t = useT()
  const percent = percentOf(item)
  const failed = item.status === 'failed'
  const done = item.status === 'done'
  const stateLabel =
    item.status === 'uploading'
      ? t('upload.state.uploading', { percent })
      : done && item.mode === 'duplicate'
        ? t('upload.state.duplicate')
        : failed
          ? `${t('upload.state.failed')}${item.error && item.error !== 'unknown' ? ` · ${t(`upload.error.${item.error === 'conflict' ? 'network' : item.error}`)}` : ''}`
          : t(`upload.state.${item.status}`)
  const showTrack =
    item.status === 'uploading' || item.status === 'paused' || item.status === 'completing'

  return (
    <li
      className={[styles.item, item.status === 'paused' ? styles.paused : null]
        .filter(Boolean)
        .join(' ')}
      data-upload-item
      data-status={item.status}
    >
      {item.preview?.kind === 'image' ? (
        <img className={styles.thumb} src={item.preview.url} alt="" />
      ) : (
        <span className={styles.thumb} aria-hidden="true">
          {item.preview?.media === 'video'
            ? 'mov'
            : (item.name.split('.').pop()?.slice(0, 4) ?? '')}
        </span>
      )}
      <div className={styles.main}>
        <span className={styles.name}>{item.name}</span>
        <span
          className={[styles.state, failed ? styles.failed : null].filter(Boolean).join(' ')}
          data-state-label
        >
          {stateLabel}
        </span>
        {showTrack ? (
          <div
            className={styles.track}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={item.size}
            aria-valuenow={bytesSent(item)}
          >
            <div className={styles.fill} style={{ width: `${percent}%` }} />
          </div>
        ) : null}
      </div>
      <div className={styles.actions}>
        {failed ? (
          <Button variant="quiet" small onClick={() => onRetry(item.clientId)}>
            {t('upload.retry')}
          </Button>
        ) : !done && item.status !== 'cancelled' ? (
          <Button
            variant="quiet"
            small
            onClick={() => onCancel(item.clientId)}
            aria-label={t('common.cancel')}
          >
            {t('common.cancel')}
          </Button>
        ) : null}
      </div>
    </li>
  )
}

interface ListProps {
  items: UploadItemState[]
  onRetry: (id: string) => void
  onCancel: (id: string) => void
}

export function UploadList({ items, onRetry, onCancel }: ListProps) {
  return (
    <ul className={styles.list} data-upload-list>
      {items.map((item) => (
        <UploadItem key={item.clientId} item={item} onRetry={onRetry} onCancel={onCancel} />
      ))}
    </ul>
  )
}
