import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { FaceChip } from '~/components/FaceChip'
import { ItemViewer } from '~/components/ItemViewer'
import { MediaTile } from '~/components/MediaTile'
import { PageHeader } from '~/components/PageHeader'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useToast } from '~/components/Toast'
import { useLocale, useT } from '~/i18n'
import { formatEventDate, formatNumber } from '~/lib/format'
import { requireSession } from '~/lib/guards'
import { meQuery } from '~/lib/queries/me'
import { createZip } from '~/lib/queries/media'
import { yearQuery, yearsQuery } from '~/lib/queries/yearbook'
import styles from '~/styles/pages/year.module.css'

export const Route = createFileRoute('/year/$year')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  loader: async ({ context: { queryClient }, params }) => {
    await Promise.all([
      queryClient.ensureQueryData(yearQuery(Number(params.year))).catch(() => undefined),
      queryClient.ensureQueryData(yearsQuery()).catch(() => undefined),
    ])
  },
  component: YearPage,
})

function YearPage() {
  const t = useT()
  const locale = useLocale()
  const toast = useToast()
  const navigate = useNavigate()
  const { year: yearParam } = Route.useParams()
  const year = Number(yearParam)
  const recap = useQuery(yearQuery(year))
  const years = useQuery(yearsQuery())
  const me = useQuery(meQuery())
  const [openId, setOpenId] = useState<string | null>(null)
  const [zipping, setZipping] = useState(false)

  const data = recap.data
  const top = data?.top_people[0]
  const portrait = data?.portrait
  const portraitSrc =
    portrait?.variants?.large ?? portrait?.variants?.medium ?? portrait?.variants?.small
  const allOfYou = [
    ...(data?.best_of_you ?? []),
    ...(data?.events.flatMap((e) => e.of_you_items ?? []) ?? []),
  ].filter((item, i, arr) => arr.findIndex((x) => x.id === item.id) === i)

  const shareYear = async () => {
    const url = window.location.href
    const title = t('year.shareTitle', { year })
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title, url })
        return
      } catch {
        // fall back to copy
      }
    }
    try {
      await navigator.clipboard.writeText(url)
      toast(t('common.copied'))
    } catch {
      toast(t('common.error'))
    }
  }

  const saveAll = async () => {
    if (allOfYou.length === 0) return
    setZipping(true)
    try {
      const ticket = await createZip(allOfYou.map((i) => i.id))
      window.location.assign(ticket.url)
    } catch {
      toast(t('common.error'))
    } finally {
      setZipping(false)
    }
  }

  return (
    <>
      <PageHeader
        title={t('year.title', { year })}
        back="/"
        right={
          years.data && years.data.length > 1 ? (
            <select
              className={styles.switcher}
              aria-label={t('year.switch')}
              value={year}
              onChange={(ev) => navigate({ to: '/year/$year', params: { year: ev.target.value } })}
            >
              {years.data.map((y) => (
                <option key={y.year} value={y.year}>
                  {y.year}
                </option>
              ))}
            </select>
          ) : null
        }
      />
      <main className={`${styles.main} has-bar`} data-year={year}>
        {recap.isError && !data ? (
          <EmptyState kind="offline" />
        ) : data && data.moments === 0 ? (
          <EmptyState kind="no-year" />
        ) : data ? (
          <>
            <header className={styles.hero}>
              {portraitSrc ? (
                <img className={styles.heroImage} src={portraitSrc} alt="" fetchPriority="high" />
              ) : null}
              <div className={styles.heroText}>
                <span className={styles.heroYear}>{year}</span>
                <h2 className={styles.heroName}>{me.data?.display_name ?? ''}</h2>
                <p className={styles.heroLine} data-year-summary>
                  {top
                    ? t('year.summary', {
                        moments: formatNumber(data.moments, locale),
                        events: data.events.length,
                        name: top.display_name,
                      })
                    : t('year.summaryNoPeople', {
                        moments: formatNumber(data.moments, locale),
                        events: data.events.length,
                      })}
                </p>
              </div>
            </header>

            {data.best_of_you.length ? (
              <section className={styles.section}>
                <h2 className="eyebrow">{t('year.bestShots')}</h2>
                <SimpleGrid>
                  {data.best_of_you.map((item, i) => (
                    <MediaTile
                      key={item.id}
                      item={item}
                      priority={i < 6}
                      onOpen={() => setOpenId(item.id)}
                    />
                  ))}
                </SimpleGrid>
              </section>
            ) : null}

            {data.top_people.length ? (
              <section className={styles.section}>
                <h2 className="eyebrow">{t('year.topPeople')}</h2>
                <div className={styles.people}>
                  {data.top_people.map((p) => (
                    <FaceChip
                      key={p.person_id ?? p.display_name}
                      name={p.display_name}
                      src={p.crop_url}
                      count={p.count}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            <section className={styles.section}>
              <h2 className="eyebrow">{t('common.events', { count: data.events.length })}</h2>
              <ul className={styles.events}>
                {data.events.map((e) => (
                  <li key={e.slug} className={styles.eventRow}>
                    <Link to="/e/$slug" params={{ slug: e.slug }} className={styles.eventTitle}>
                      {e.title}
                    </Link>
                    <span className={styles.eventMeta}>
                      {formatEventDate(e.starts_at, locale)} ·{' '}
                      <span className="you">{t('common.ofYou', { count: e.of_you })}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          </>
        ) : null}
      </main>
      <BottomBar>
        <Button variant="secondary" onClick={shareYear} data-share-year>
          {t('year.shareMyYear')}
        </Button>
        <Button onClick={saveAll} busy={zipping} disabled={allOfYou.length === 0}>
          {t('year.saveAll')}
        </Button>
      </BottomBar>
      <ItemViewer
        items={allOfYou}
        openId={openId}
        title={t('year.title', { year })}
        onClose={() => setOpenId(null)}
        onNavigate={setOpenId}
      />
    </>
  )
}
