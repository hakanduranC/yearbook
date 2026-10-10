import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { FaceChip } from '~/components/FaceChip'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { Face, Person } from '~/lib/api/types'
import { requireHost } from '~/lib/guards'
import { keys } from '~/lib/queries/keys'
import {
  faceCropUrl,
  faceNotPerson,
  listPersonFaces,
  mergePeople,
  peopleQuery,
  splitPerson,
} from '~/lib/queries/people'
import styles from '~/styles/pages/people.module.css'

export const Route = createFileRoute('/e/$slug/people/manage')({
  beforeLoad: async ({ context: { queryClient }, params, location }) => {
    await requireHost(queryClient, params.slug, location.href)
  },
  loader: async ({ context: { queryClient }, params }) => {
    await queryClient.ensureQueryData(peopleQuery(params.slug)).catch(() => undefined)
  },
  component: ManagePeople,
})

function ManagePeople() {
  const t = useT()
  const toast = useToast()
  const { slug } = Route.useParams()
  const queryClient = useQueryClient()
  const people = useQuery(peopleQuery(slug))
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const [open, setOpen] = useState<string | null>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: keys.people(slug) })
    queryClient.invalidateQueries({ queryKey: keys.personAll() })
    queryClient.invalidateQueries({ queryKey: keys.mediaAll(slug) })
  }

  const merge = useMutation({
    mutationFn: (ids: string[]) => mergePeople(ids),
    onSuccess: () => {
      setSelected(new Set())
      refresh()
      toast(t('people.merged'))
    },
    onError: () => toast(t('common.error')),
  })

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const persons = people.data?.persons ?? []

  return (
    <>
      <PageHeader title={t('people.manageTitle')} back="/e/$slug/people" backParams={{ slug }} />
      <main className={`page ${styles.main} has-bar`} data-manage-people>
        <p className={styles.muted}>{t('people.manageLead')}</p>
        {persons.length === 0 && people.isSuccess ? (
          <EmptyState kind="no-people" />
        ) : (
          <ul className={styles.manageList}>
            {persons.map((p) => (
              <li key={p.id} className={styles.manageRow} data-manage-person={p.id}>
                <div className={styles.manageHead}>
                  <FaceChip
                    name={p.display_name}
                    you={p.is_me}
                    src={p.crop_url}
                    caption={t('people.faces', { count: p.face_count })}
                    selected={selected.has(p.id)}
                    onClick={() => toggle(p.id)}
                    data-person={p.id}
                  />
                  <Button
                    variant="quiet"
                    small
                    aria-expanded={open === p.id}
                    onClick={() => setOpen(open === p.id ? null : p.id)}
                    data-faces-toggle
                  >
                    {open === p.id ? t('nav.close') : t('people.faces', { count: p.face_count })}
                  </Button>
                </div>
                {open === p.id ? <FaceStrip slug={slug} person={p} onChanged={refresh} /> : null}
              </li>
            ))}
          </ul>
        )}
      </main>
      <BottomBar>
        <Button
          variant="secondary"
          onClick={() => setSelected(new Set())}
          disabled={!selected.size}
        >
          {t('common.cancel')}
        </Button>
        <Button
          disabled={selected.size < 2}
          busy={merge.isPending}
          onClick={() => merge.mutate([...selected])}
          data-merge
        >
          {t('people.merge', { count: selected.size })}
        </Button>
      </BottomBar>
    </>
  )
}

/** Faces of one person: tap to pick, then split them off, or mark a single one as not this person. */
function FaceStrip({
  slug,
  person,
  onChanged,
}: {
  slug: string
  person: Person
  onChanged: () => void
}) {
  const t = useT()
  const toast = useToast()
  const faces = useQuery({
    queryKey: keys.personFaces(person.id),
    queryFn: () => listPersonFaces(slug, person.id),
  })
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set())

  const split = useMutation({
    mutationFn: (ids: string[]) => splitPerson(person.id, ids),
    onSuccess: () => {
      setPicked(new Set())
      onChanged()
      faces.refetch()
      toast(t('people.splitDone'))
    },
    onError: () => toast(t('common.error')),
  })
  const notPerson = useMutation({
    mutationFn: (face: Face) => faceNotPerson(face.id),
    onSuccess: () => {
      onChanged()
      faces.refetch()
      toast(t('lightbox.reported'))
    },
    onError: () => toast(t('common.error')),
  })

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <div className={styles.strip} data-face-strip={person.id}>
      <p className={styles.muted}>{t('people.selectFaces')}</p>
      {faces.isPending ? (
        <p className={styles.muted}>{t('common.loading')}</p>
      ) : (
        <div className={styles.stripFaces}>
          {(faces.data ?? []).map((face) => (
            <div key={face.id} className={styles.stripFace}>
              <button
                type="button"
                className={[styles.stripImg, picked.has(face.id) ? styles.stripPicked : null]
                  .filter(Boolean)
                  .join(' ')}
                aria-pressed={picked.has(face.id)}
                onClick={() => toggle(face.id)}
                data-face={face.id}
              >
                <img src={face.crop_url ?? faceCropUrl(face.id)} alt="" loading="lazy" />
              </button>
              <Button
                variant="quiet"
                small
                onClick={() => notPerson.mutate(face)}
                busy={notPerson.isPending && notPerson.variables?.id === face.id}
                data-face-not-person
              >
                {t('people.notThisPerson')}
              </Button>
            </div>
          ))}
        </div>
      )}
      <div className={styles.stripActions}>
        <Button
          small
          variant="secondary"
          disabled={picked.size === 0}
          busy={split.isPending}
          onClick={() => split.mutate([...picked])}
          data-split
        >
          {t('people.split', { count: picked.size })}
        </Button>
      </div>
    </div>
  )
}
