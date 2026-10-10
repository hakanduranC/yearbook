import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery,
} from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Button } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { SwitchRow } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { PhotoGrid } from '~/components/PhotoGrid'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { MediaFilter, Person } from '~/lib/api/types'
import { useClaim } from '~/lib/claim'
import { loadEvent } from '~/lib/guards'
import { eventQuery, isHost } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import { mediaQuery } from '~/lib/queries/media'
import { personQuery, unclaimPerson, updatePerson } from '~/lib/queries/people'
import { useSelection } from '~/lib/selection'
import styles from '~/styles/pages/people.module.css'

export const Route = createFileRoute('/e/$slug/people/$personId')({
  loader: async ({ context: { queryClient }, params }) => {
    await loadEvent(queryClient, params.slug)
    await queryClient.ensureQueryData(personQuery(params.personId)).catch(() => undefined)
  },
  component: PersonPage,
})

function PersonPage() {
  const t = useT()
  const toast = useToast()
  const { slug, personId } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const person = useQuery(personQuery(personId))
  const filter: MediaFilter = `person:${personId}`
  const media = useInfiniteQuery(mediaQuery(slug, filter))
  const selection = useSelection()
  const claim = useClaim(slug)
  const [name, setName] = useState(person.data?.display_name ?? '')
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (!editing) setName(person.data?.display_name ?? '')
  }, [person.data?.display_name, editing])

  const setPerson = (p: Person) => {
    queryClient.setQueryData(keys.person(p.id), p)
    queryClient.invalidateQueries({ queryKey: keys.people(slug) })
  }

  const rename = useMutation({
    mutationFn: (display_name: string | null) => updatePerson(personId, { display_name }),
    onSuccess: (p) => {
      setPerson(p)
      setEditing(false)
      toast(t('common.saved'))
    },
    onError: () => toast(t('common.error')),
  })
  const hide = useMutation({
    mutationFn: (hidden: boolean) => updatePerson(personId, { hidden }),
    onSuccess: setPerson,
    onError: () => toast(t('common.error')),
  })
  const unclaim = useMutation({
    mutationFn: () => unclaimPerson(personId),
    onSuccess: (p) => {
      setPerson(p)
      queryClient.invalidateQueries({ queryKey: keys.event(slug), exact: true })
      queryClient.invalidateQueries({ queryKey: keys.mediaAll(slug) })
      queryClient.invalidateQueries({ queryKey: keys.me() })
      toast(t('people.unclaimed'))
    },
    onError: () => toast(t('common.error')),
  })

  const p = person.data
  const host = isHost(event)
  const canHide = host || p?.is_me === true
  const title = p?.is_me ? t('common.you') : (p?.display_name ?? t('people.unknown'))

  return (
    <>
      <PageHeader title={title} back="/e/$slug/people" backParams={{ slug }} />
      <main className={styles.personMain} data-person-page={personId}>
        {p ? (
          <header className={styles.personHead}>
            {p.crop_url ? (
              <img
                className={[styles.personCrop, p.is_me ? styles.personCropYou : null]
                  .filter(Boolean)
                  .join(' ')}
                src={p.crop_url}
                alt=""
              />
            ) : (
              <span className={styles.personCrop} />
            )}
            <div className={styles.personText}>
              <form
                className={styles.nameForm}
                onSubmit={(ev) => {
                  ev.preventDefault()
                  rename.mutate(name.trim() || null)
                }}
              >
                <input
                  className={[styles.nameInput, p.is_me ? styles.nameYou : null]
                    .filter(Boolean)
                    .join(' ')}
                  value={name}
                  placeholder={t('people.namePlaceholder')}
                  aria-label={t('people.nameField')}
                  maxLength={80}
                  onFocus={() => setEditing(true)}
                  onChange={(ev) => setName(ev.target.value)}
                  onBlur={() => {
                    if (name.trim() !== (p.display_name ?? '')) rename.mutate(name.trim() || null)
                    else setEditing(false)
                  }}
                  data-person-name
                />
              </form>
              <span className={styles.muted}>
                {t('people.inPhotos', { count: p.media_count ?? p.face_count })}
                {p.hidden ? ` · ${t('people.hidden')}` : ''}
              </span>
              <div className={styles.personActions}>
                {p.is_me ? (
                  <Button
                    small
                    variant="secondary"
                    busy={unclaim.isPending}
                    onClick={() => unclaim.mutate()}
                    data-unclaim
                  >
                    {t('people.notMe')}
                  </Button>
                ) : (
                  <Button
                    small
                    busy={claim.isPending}
                    onClick={() =>
                      claim
                        .mutateAsync(personId)
                        .then(() => toast(t('people.claimed')))
                        .catch(() => toast(t('common.error')))
                    }
                    data-claim
                  >
                    {t('people.thisIsMe')}
                  </Button>
                )}
              </div>
            </div>
          </header>
        ) : null}
        {p && canHide ? (
          <div className={styles.hideRow}>
            <SwitchRow
              label={t('people.hide')}
              checked={p.hidden}
              onChange={(v) => hide.mutate(v)}
            />
          </div>
        ) : null}
        {media.isError && !media.data ? (
          <EmptyState kind="offline" />
        ) : media.data?.pages.every((pg) => pg.items.length === 0) ? (
          <EmptyState kind="no-photos" />
        ) : (
          <PhotoGrid
            slug={slug}
            filter={filter}
            pages={media.data?.pages}
            timeZone={event.timezone}
            selectMode={selection.active}
            selected={selection.selected}
            onToggle={selection.toggle}
            hasNextPage={media.hasNextPage}
            isFetchingNextPage={media.isFetchingNextPage}
            fetchNextPage={() => media.fetchNextPage()}
          />
        )}
      </main>
    </>
  )
}
