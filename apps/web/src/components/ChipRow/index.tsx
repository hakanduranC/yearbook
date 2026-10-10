import type { ReactNode } from 'react'
import styles from './ChipRow.module.css'

/** Horizontal, scrollable row of chips. Children are buttons or links styled by `chipClass`. */
export function ChipRow({ children, wrap }: { children: ReactNode; wrap?: boolean }) {
  return (
    <div className={[styles.row, wrap ? styles.wrap : null].filter(Boolean).join(' ')}>
      {children}
    </div>
  )
}

export function chipClass(options: { you?: boolean; active?: boolean; quiet?: boolean } = {}) {
  return [
    styles.chip,
    options.you ? styles.you : null,
    options.active ? styles.active : null,
    options.quiet ? styles.quiet : null,
  ]
    .filter(Boolean)
    .join(' ')
}
