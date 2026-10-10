import type { ReactNode } from 'react'
import styles from './SimpleGrid.module.css'

interface Props {
  children: ReactNode
  /** Columns on phones; wider screens add more. */
  columns?: 2 | 3
  /** Shimmering placeholders instead of content. */
  skeleton?: number
  className?: string
}

export function SimpleGrid({ children, columns = 3, skeleton, className }: Props) {
  return (
    <div
      className={[styles.grid, columns === 2 ? styles.two : styles.three, className]
        .filter(Boolean)
        .join(' ')}
      data-skeleton={skeleton ? 'true' : undefined}
    >
      {skeleton
        ? Array.from({ length: skeleton }, (_, i) => (
            <span key={i} className={styles.skeleton} aria-hidden="true" />
          ))
        : children}
    </div>
  )
}
