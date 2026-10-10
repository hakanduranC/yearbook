import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { PhotoCell } from '~/components/PhotoCell'
import { useLocale, useT } from '~/i18n'
import type { GridItem, MediaFilter, MediaPage } from '~/lib/api/types'
import { formatGroupDay } from '~/lib/format'
import { columnsFor, type Group, type Row, rowModel } from '~/lib/grouping'
import styles from './PhotoGrid.module.css'

const HEADER_HEIGHT = 44
const GAP = 2
const SSR_WIDTH = 390

interface Props {
  slug: string
  filter: MediaFilter
  pages: MediaPage[] | undefined
  timeZone?: string
  selectMode: boolean
  selected: ReadonlySet<string>
  onToggle: (id: string) => void
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
}

const useIsoLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

function useColumns(): [number, number] {
  const [width, setWidth] = useState(SSR_WIDTH)
  useIsoLayoutEffect(() => {
    const update = () => setWidth(document.documentElement.clientWidth)
    update()
    const queries = ['(min-width: 600px)', '(min-width: 1024px)', '(min-width: 1440px)'].map((q) =>
      matchMedia(q),
    )
    for (const q of queries) q.addEventListener('change', update)
    window.addEventListener('resize', update)
    return () => {
      for (const q of queries) q.removeEventListener('change', update)
      window.removeEventListener('resize', update)
    }
  }, [])
  return [columnsFor(width), width]
}

export function groupLabel(
  group: Group,
  t: ReturnType<typeof useT>,
  locale: ReturnType<typeof useLocale>,
  timeZone?: string,
) {
  const part = t(`photos.group.${group.label}`)
  const day = group.start ? formatGroupDay(group.start, locale, timeZone) : null
  return { part, day }
}

export function PhotoGrid({
  slug,
  filter,
  pages,
  timeZone,
  selectMode,
  selected,
  onToggle,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: Props) {
  const t = useT()
  const locale = useLocale()
  const [columns, width] = useColumns()
  const model = useMemo(() => rowModel(pages, columns), [pages, columns])
  const cellSize = (width - GAP * (columns - 1)) / columns
  const listRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)

  useIsoLayoutEffect(() => {
    setScrollMargin(listRef.current?.offsetTop ?? 0)
  }, [])

  const virtualizer = useWindowVirtualizer({
    count: model.rows.length,
    estimateSize: (index) =>
      model.rows[index]?.type === 'header' ? HEADER_HEIGHT : cellSize + GAP,
    overscan: 6,
    scrollMargin,
    initialRect: { width: SSR_WIDTH, height: 844 },
    getItemKey: (index) => model.rows[index]?.key ?? index,
  })

  const virtualRows = virtualizer.getVirtualItems()

  // Re-measure when the column count or cell size changes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: cellSize and columns are the triggers
  useEffect(() => {
    virtualizer.measure()
  }, [virtualizer, cellSize, columns])

  // Infinite scroll near the end.
  const last = virtualRows[virtualRows.length - 1]
  useEffect(() => {
    if (!last) return
    if (last.index >= model.rows.length - 4 && hasNextPage && !isFetchingNextPage) fetchNextPage()
  }, [last, model.rows.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  // Current sticky group label: last header at or before the first visible row.
  const first = virtualRows[0]
  const currentGroup = useMemo(() => {
    if (!first) return null
    for (let i = first.index; i >= 0; i--) {
      const row = model.rows[i]
      if (row?.type === 'header') return row.group
    }
    return null
  }, [first, model.rows])

  const firstVisibleIsHeader = first ? model.rows[first.index]?.type === 'header' : true

  return (
    <div className={styles.wrap}>
      {currentGroup && !firstVisibleIsHeader ? (
        <div className={styles.sticky} aria-hidden="true">
          <span className={styles.stickyLabel}>
            {groupLabel(currentGroup, t, locale, timeZone).part}
          </span>
        </div>
      ) : null}
      <div
        ref={listRef}
        className={styles.list}
        style={{ height: virtualizer.getTotalSize() }}
        data-grid
      >
        {virtualRows.map((virtualRow) => {
          const row = model.rows[virtualRow.index]
          if (!row) return null
          const style = {
            transform: `translateY(${virtualRow.start - scrollMargin}px)`,
            height: virtualRow.size,
          }
          if (row.type === 'header') {
            const { part, day } = groupLabel(row.group, t, locale, timeZone)
            return (
              <div
                key={virtualRow.key}
                className={styles.header}
                style={style}
                data-group={row.group.label}
              >
                <span>{part}</span>
                {day ? <span className={styles.headerDay}>{day}</span> : null}
              </div>
            )
          }
          return (
            <GridRow
              key={virtualRow.key}
              row={row}
              style={style}
              columns={columns}
              slug={slug}
              filter={filter}
              selectMode={selectMode}
              selected={selected}
              onToggle={onToggle}
              priority={virtualRow.index < 6}
            />
          )
        })}
      </div>
    </div>
  )
}

function GridRow({
  row,
  style,
  columns,
  slug,
  filter,
  selectMode,
  selected,
  onToggle,
  priority,
}: {
  row: Extract<Row, { type: 'row' }>
  style: React.CSSProperties
  columns: number
  slug: string
  filter: MediaFilter
  selectMode: boolean
  selected: ReadonlySet<string>
  onToggle: (id: string) => void
  priority: boolean
}) {
  return (
    <div
      className={styles.row}
      style={{ ...style, gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {row.items.map((item: GridItem) => (
        <PhotoCell
          key={item.id}
          item={item}
          slug={slug}
          filter={filter}
          selectMode={selectMode}
          selected={selected.has(item.id)}
          onToggle={onToggle}
          priority={priority}
        />
      ))}
    </div>
  )
}
