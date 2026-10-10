import { type ReactNode, useEffect, useRef } from 'react'
import styles from './Sheet.module.css'

interface Props {
  open: boolean
  onClose: () => void
  title?: ReactNode
  body?: ReactNode
  children: ReactNode
  labelledBy?: string
}

/** Bottom sheet on a native <dialog> with a scrim; Esc and scrim taps close it. */
export function Sheet({ open, onClose, title, body, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const openRef = useRef(open)
  openRef.current = open

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Esc closes via onCancel; the click only catches scrim taps
    <dialog
      ref={ref}
      className={styles.dialog}
      // `close` fires asynchronously; only a close the parent did not ask for counts as a user close.
      onClose={() => {
        if (openRef.current) onClose()
      }}
      onCancel={(ev) => {
        ev.preventDefault()
        onClose()
      }}
      onClick={(ev) => {
        if (ev.target === ev.currentTarget) onClose()
      }}
    >
      <div className={styles.panel}>
        <div className={styles.grabber} aria-hidden="true" />
        {title ? <h2 className={styles.title}>{title}</h2> : null}
        {body ? <p className={styles.body}>{body}</p> : null}
        {children}
      </div>
    </dialog>
  )
}
