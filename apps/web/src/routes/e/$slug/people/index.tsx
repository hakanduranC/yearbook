import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'
import { Button, ButtonLink } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { FaceChip } from '~/components/FaceChip'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { Person } from '~/lib/api/types'
import { useClaim } from '~/lib/claim'
import { loadEvent } from '~/lib/guards'
import { eventQuery, isHost } from '~/lib/queries/event'
import { peopleQuery } from '~/lib/queries/people'
import styles from '~/styles/pages/people.module.css'

export const Route = createFileRoute('/e/$slug/people/')({
  loader: async ({ context: { queryClient }, params }) => {
    await loadEvent(queryClient, params.slug)
    await queryClient.ensureQueryData(peopleQuery(params.slug)).catch(() => undefined)
  },
  component: PeoplePage,
})

function PeoplePage() {
  const t = useT()
  const toast = useToast()
  const { slug } = Route.useParams()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const people = useQuery(peopleQuery(slug))
  const claim = useClaim(slug)
  const [dismissed, setDismissed] = useState(false)

  const persons = people.data?.persons ?? []
  const suggested = persons.find((p) => p.suggested_me && !p.is_me)
  const analyzing = people.data?.analyzing || event.counts.processing > 0
  const facesDone = event.counts.faces_done ?? event.counts.ready
  const total = event.counts.photos + event.counts.videos

  const confirm = async (person: Person) => {
    try {
      await claim.mutateAsync(person.id)
      toast(t('people.claimed'))
    } catch {
      toast(t('common.error'))
    }
  }

  return (
    <>
      <PageHeader
        title={t('people.title')}
        back="/e/$slug"
        backParams={{ slug }}
        right={
          isHost(event) ? (
            <ButtonLink
              to="/e/$slug/people/manage"
              params={{ slug }}
              variant="quiet"
              small
              data-manage
            >
              {t('people.manage')}
            </ButtonLink>
          ) : null
        }
      />
      <main className={`page ${styles.main}`} data-people>
        <p className={styles.privacy}>
          {t('people.privacy')}{' '}
          <Link to="/settings" className={styles.privacyLink}>
            {t('people.privacyLink')}
          </Link>
        </p>
        {suggested && !dismissed ? (
          <section className={styles.isYou} data-is-this-you>
            {suggested.crop_url ? (
              <img className={styles.isYouCrop} src={suggested.crop_url} alt="" />
            ) : (
              <span className={styles.isYouCrop} />
            )}
            <div className={styles.isYouText}>
              <h2 className={styles.isYouTitle}>{t('people.isThisYou')}</h2>
              <p className={styles.muted}>{t('people.isThisYouBody')}</p>
              <div className={styles.isYouActions}>
                <Button small busy={claim.isPending} onClick={() => confirm(suggested)} data-claim>
                  {t('people.thisIsMe')}
                </Button>
                <Button small variant="quiet" onClick={() => setDismissed(true)} data-not-me>
                  {t('people.notMe')}
                </Button>
              </div>
            </div>
          </section>
        ) : null}
        {analyzing ? (
          <p className={styles.analyzing} role="status" data-analyzing>
            {t('people.analyzing', { done: Math.min(facesDone, total), total })}
          </p>
        ) : null}
        {people.isError && !people.data ? (
          <EmptyState kind="offline" />
        ) : persons.length === 0 && people.isSuccess ? (
          <EmptyState kind={analyzing ? 'analyzing' : 'no-people'} />
        ) : (
          <div className={styles.grid}>
            {persons.map((p) => (
              <FaceChip
                key={p.id}
                name={p.display_name}
                you={p.is_me}
                src={p.crop_url}
                count={p.media_count ?? p.face_count}
                size="lg"
                link={{ to: '/e/$slug/people/$personId', params: { slug, personId: p.id } }}
                data-person={p.id}
              />
            ))}
          </div>
        )}
        {people.data?.unnamed_count ? (
          <p className={styles.muted}>
            {t('people.unnamed', { count: people.data.unnamed_count })}
          </p>
        ) : null}
      </main>
    </>
  )
}
