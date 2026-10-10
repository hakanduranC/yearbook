import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { EmptyState } from '~/components/EmptyState'
import { FaceChip } from '~/components/FaceChip'
import { PageHeader } from '~/components/PageHeader'
import { Suggestions } from '~/components/Suggestions'
import { useT } from '~/i18n'
import { requireSession } from '~/lib/guards'
import { groupByEvent } from '~/lib/people'
import { eventsQuery } from '~/lib/queries/event'
import { myPeopleQuery, suggestionsQuery } from '~/lib/queries/people'
import formStyles from '~/styles/pages/form.module.css'
import styles from '~/styles/pages/people.module.css'

export const Route = createFileRoute('/people')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      queryClient.ensureQueryData(myPeopleQuery()).catch(() => undefined),
      queryClient.ensureQueryData(suggestionsQuery()).catch(() => undefined),
    ])
  },
  component: MyPeople,
})

function MyPeople() {
  const t = useT()
  const people = useQuery(myPeopleQuery())
  const events = useQuery(eventsQuery())
  const titleOf = (slug: string) => events.data?.items.find((e) => e.slug === slug)?.title ?? slug
  const persons = people.data?.persons ?? []

  return (
    <>
      <PageHeader title={t('myPeople.title')} back="/" />
      <main className={`page ${styles.main}`} data-my-people>
        <p className={formStyles.lead}>{t('myPeople.lead')}</p>
        <Suggestions />
        {people.isSuccess && persons.length === 0 ? (
          <EmptyState kind="no-people" body={t('myPeople.empty')} />
        ) : (
          groupByEvent(persons).map(([slug, list]) => (
            <section key={slug} className={styles.eventGroup}>
              <h2 className="eyebrow">{titleOf(slug)}</h2>
              <div className={styles.grid}>
                {list.map((p) => (
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
            </section>
          ))
        )}
      </main>
    </>
  )
}
