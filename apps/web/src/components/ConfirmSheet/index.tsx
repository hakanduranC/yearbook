import type { ReactNode } from 'react'
import { Button } from '~/components/Button'
import { Sheet } from '~/components/Sheet'
import { useT } from '~/i18n'
import styles from './ConfirmSheet.module.css'

interface Props {
  open: boolean
  title: ReactNode
  body?: ReactNode
  confirmLabel: ReactNode
  danger?: boolean
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
}

/** A bottom sheet with one question and two answers. Danger confirms are outlined in rose. */
export function ConfirmSheet({
  open,
  title,
  body,
  confirmLabel,
  danger,
  busy,
  onConfirm,
  onClose,
}: Props) {
  const t = useT()
  return (
    <Sheet open={open} onClose={onClose} title={title} body={body}>
      <div className={styles.actions}>
        <Button
          variant={danger ? 'danger' : 'primary'}
          busy={busy}
          onClick={onConfirm}
          data-confirm
        >
          {confirmLabel}
        </Button>
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          {t('common.cancel')}
        </Button>
      </div>
    </Sheet>
  )
}
