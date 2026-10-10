import { useEffect, useState } from 'react'
import { Button } from '~/components/Button'
import { SwitchRow } from '~/components/Field'
import { Sheet } from '~/components/Sheet'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { Share } from '~/lib/api/types'
import { shareAlbum } from '~/lib/queries/albums'
import styles from './ShareSheet.module.css'

interface Props {
  open: boolean
  albumId: string | null
  title: string
  onClose: () => void
}

/** Creates a read-only link for an album: allow-download toggle, then the link with copy and native share. */
export function ShareSheet({ open, albumId, title, onClose }: Props) {
  const t = useT()
  const toast = useToast()
  const [allowDownload, setAllowDownload] = useState(true)
  const [share, setShare] = useState<Share | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) setShare(null)
  }, [open])

  const create = async () => {
    if (!albumId) return
    setBusy(true)
    try {
      setShare(await shareAlbum(albumId, allowDownload))
    } catch {
      toast(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    if (!share) return
    try {
      await navigator.clipboard.writeText(share.url)
      toast(t('common.copied'))
    } catch {
      toast(t('common.error'))
    }
  }

  const native = async () => {
    if (!share) return
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title, url: share.url })
        return
      } catch {
        // fall back to copy
      }
    }
    copy()
  }

  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <div className={styles.body} data-share-sheet>
        {share ? (
          <>
            <output className={styles.link} data-share-url>
              {share.url}
            </output>
            <p className={styles.hint}>
              {share.allow_download ? t('album.allowDownload') : t('album.downloadOff')}
            </p>
            <div className={styles.actions}>
              <Button onClick={copy} data-copy-link>
                {t('common.copy')}
              </Button>
              <Button variant="secondary" onClick={native}>
                {t('common.share')}
              </Button>
            </div>
          </>
        ) : (
          <>
            <SwitchRow
              label={t('album.allowDownload')}
              checked={allowDownload}
              onChange={setAllowDownload}
            />
            <div className={styles.actions}>
              <Button onClick={create} busy={busy} disabled={!albumId} data-create-link>
                {t('album.createLink')}
              </Button>
            </div>
          </>
        )}
      </div>
    </Sheet>
  )
}
