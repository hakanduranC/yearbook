import { useMemo } from 'react'
import { Lightbox } from '~/components/Lightbox'
import type { GridItem } from '~/lib/api/types'

interface Props {
  items: GridItem[]
  openId: string | null
  title: string
  timeZone?: string
  onClose: () => void
  onNavigate: (id: string) => void
  onToggleLike?: (id: string, liked: boolean) => void
}

/** The lightbox over a plain list, for curated pages that have no modal route: albums, shares, the year. */
export function ItemViewer({
  items,
  openId,
  title,
  timeZone,
  onClose,
  onNavigate,
  onToggleLike,
}: Props) {
  const index = useMemo(() => items.findIndex((i) => i.id === openId), [items, openId])
  const item = index >= 0 ? items[index] : null
  if (!item) return null
  return (
    <Lightbox
      item={item}
      index={index + 1}
      total={items.length}
      previous={index > 0 ? (items[index - 1] ?? null) : null}
      next={index < items.length - 1 ? (items[index + 1] ?? null) : null}
      eventTitle={title}
      timeZone={timeZone}
      onClose={onClose}
      onNavigate={onNavigate}
      onToggleLike={onToggleLike ?? (() => {})}
    />
  )
}
