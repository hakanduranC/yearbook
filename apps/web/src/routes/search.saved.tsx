import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'
import { Button } from '~/components/Button'
import { ConfirmSheet } from '~/components/ConfirmSheet'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { SavedCommand } from '~/lib/api/types'
import { requireSession } from '~/lib/guards'
import { deleteSavedCommand, savedCommandsQuery } from '~/lib/queries/agent'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/search/saved')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  loader: async ({ context: { queryClient } }) => {
    await queryClient.ensureQueryData(savedCommandsQuery(null)).catch(() => undefined)
  },
  component: SavedCommands,
})

function SavedCommands() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const commands = useQuery(savedCommandsQuery(null))
  const [doomed, setDoomed] = useState<SavedCommand | null>(null)
  const remove = useMutation({
    mutationFn: (id: string) => deleteSavedCommand(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['commands'] })
      setDoomed(null)
    },
    onError: () => toast(t('common.error')),
  })

  return (
    <>
      <PageHeader title={t('search.savedTitle')} back="/search" />
      <main className={`page page--narrow ${styles.main}`} data-saved-commands>
        {commands.data?.length === 0 ? (
          <p className={styles.lead}>{t('search.savedEmpty')}</p>
        ) : (
          <ul className={styles.list}>
            {(commands.data ?? []).map((c) => (
              <li key={c.id} className={styles.commandRow} data-command={c.id}>
                <div className={styles.commandText}>
                  <Link
                    to={c.event_slug ? '/e/$slug/search' : '/search'}
                    params={c.event_slug ? { slug: c.event_slug } : {}}
                    search={{ command: c.id }}
                    className={styles.commandLabel}
                  >
                    {c.label}
                  </Link>
                  <span className={styles.uploaderMeta}>
                    {c.description}
                    {c.event_slug ? ` · ${c.event_slug}` : ` · ${t('search.allEvents')}`}
                    {typeof c.run_count === 'number' && c.run_count > 0
                      ? ` · ${t('search.runs', { count: c.run_count })}`
                      : ''}
                  </span>
                  {c.kind === 'python' || c.created_by_agent ? (
                    <span className={styles.tags}>
                      {c.kind === 'python' ? (
                        <span className={styles.tag} data-tag="tool">
                          {t('search.toolTag')}
                        </span>
                      ) : null}
                      {c.created_by_agent ? (
                        <span className={`${styles.tag} ${styles.tagAgent}`} data-tag="agent">
                          {t('search.byAgent')}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                <Button variant="quiet" small onClick={() => setDoomed(c)} data-delete-command>
                  {t('common.delete')}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </main>
      <ConfirmSheet
        open={doomed !== null}
        title={t('search.deleteChip')}
        body={doomed?.label}
        confirmLabel={t('common.delete')}
        danger
        busy={remove.isPending}
        onConfirm={() => doomed && remove.mutate(doomed.id)}
        onClose={() => setDoomed(null)}
      />
    </>
  )
}
