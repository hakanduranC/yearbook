import { useEffect, useRef, useState } from 'react'
import { useT } from '~/i18n'
import { splitAttachments } from '~/lib/agent'
import type { Attachment } from '~/lib/api/types'
import styles from './Attachments.module.css'

/** Images the agent produced as a horizontal strip, other files as a download row. */
export function Attachments({ list }: { list: readonly Attachment[] }) {
  const t = useT()
  const { images, files } = splitAttachments(list)
  const [open, setOpen] = useState<number | null>(null)
  if (list.length === 0) return null
  return (
    <section className={styles.wrap} data-attachments>
      <h3 className="eyebrow">{t('search.attachments')}</h3>
      {images.length ? (
        <div className={styles.strip}>
          {images.map((a, i) => (
            <button
              key={`${a.url}-${i}`}
              type="button"
              className={styles.tile}
              onClick={() => setOpen(i)}
              aria-label={a.name}
              data-attachment-image
            >
              <img src={a.url} alt="" width={a.width} height={a.height} loading="lazy" />
            </button>
          ))}
        </div>
      ) : null}
      {files.length ? (
        <ul className={styles.files}>
          {files.map((a, i) => (
            <li key={`${a.url}-${i}`}>
              <a href={a.url} download={a.name} className={styles.file} data-attachment-file>
                <span className={styles.fileName}>{a.name}</span>
                <span className={styles.fileMeta}>{a.mime}</span>
                <span className={styles.fileAction}>{t('common.download')}</span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
      {open !== null && images[open] ? (
        <Viewer
          image={images[open]}
          index={open}
          total={images.length}
          onClose={() => setOpen(null)}
          onNavigate={setOpen}
        />
      ) : null}
    </section>
  )
}

function Viewer({
  image,
  index,
  total,
  onClose,
  onNavigate,
}: {
  image: Attachment
  index: number
  total: number
  onClose: () => void
  onNavigate: (i: number) => void
}) {
  const t = useT()
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'ArrowLeft' && index > 0) onNavigate(index - 1)
      if (ev.key === 'ArrowRight' && index < total - 1) onNavigate(index + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, total, onNavigate])
  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-label={image.name}
      onCancel={(ev) => {
        ev.preventDefault()
        onClose()
      }}
      onClose={onClose}
      data-attachment-viewer
    >
      <div className={styles.top}>
        <button type="button" className={styles.icon} onClick={onClose} aria-label={t('nav.close')}>
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
        <span>{total > 1 ? t('lightbox.counter', { index: index + 1, total }) : image.name}</span>
        <span />
      </div>
      <div className={styles.stage}>
        <img className={styles.media} src={image.url} alt={image.name} />
      </div>
      <div className={styles.footer}>
        <span className={styles.meta}>{image.name}</span>
        <a className={styles.action} href={image.url} download={image.name}>
          {t('common.download')}
        </a>
      </div>
    </dialog>
  )
}
