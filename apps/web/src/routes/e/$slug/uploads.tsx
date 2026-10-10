import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Button } from '~/components/Button'
import { PageHeader } from '~/components/PageHeader'
import { useLocale, useT } from '~/i18n'
import { formatTime } from '~/lib/format'
import { requireHost } from '~/lib/guards'
import { eventQuery } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import { hostUploadsQuery, retryMedia } from '~/lib/queries/uploads'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/e/$slug/uploads')({
  beforeLoad: async ({ context: { queryClient }, params, location }) => {
    await requireHost(queryClient, params.slug, location.href)
  },
  loader: async ({ context: { queryClient }, params }) => {
    await queryClient.ensureQueryData(hostUploadsQuery(params.slug)).catch(() => undefined)
  },
  component: HostUploadsPage,
})

function HostUploadsPage() {
  const t = useT()
  const locale = useLocale()
  const { slug } = Route.useParams()
  const queryClient = useQueryClient()
  const event = useQuery(eventQuery(slug))
  const uploads = useQuery({ ...hostUploadsQuery(slug), refetchInterval: 10_000 })
  const retry = useMutation({
    mutationFn: retryMedia,
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.hostUploads(slug) }),
  })

  const data = uploads.data
  const failedIds =
    data?.uploaders.flatMap((u) => u.items.filter((i) => i.state === 'failed').map((i) => i.id)) ??
    []

  return (
    <>
      <PageHeader title={t('uploads.title')} back="/e/$slug" backParams={{ slug }} />
      <main className={`page page--narrow ${styles.main}`}>
        <p className={styles.lead}>{t('uploads.lead')}</p>
        {data ? (
          <>
            <p className={styles.lead}>
              {t('uploads.summary', {
                total: data.status.total,
                ready: data.status.ready,
                failed: data.status.failed,
              })}
            </p>
            {failedIds.length > 0 ? (
              <div className={styles.actions}>
                <Button
                  variant="secondary"
                  busy={retry.isPending}
                  onClick={() => {
                    for (const id of failedIds) retry.mutate(id)
                  }}
                >
                  {t('uploads.retryAll')}
                </Button>
              </div>
            ) : null}
            {data.uploaders.length === 0 ? (
              <p className={styles.lead}>{t('uploads.empty')}</p>
            ) : null}
            {data.uploaders.map((u) => (
              <section key={u.guest_id ?? u.display_name}>
                <div className={styles.uploader}>
                  <span className={u.is_you ? styles.youName : undefined}>
                    {u.is_you ? t('common.you') : u.display_name}
                  </span>
                  <span className={styles.uploaderMeta}>
                    {u.ready}/{u.total}
                    {u.failed ? ` · ${u.failed} ${t('uploads.state.failed')}` : ''}
                  </span>
                </div>
                <ul className={styles.list}>
                  {u.items.map((item) => (
                    <li key={item.id} className={styles.row}>
                      {item.thumb ? (
                        <img className={styles.thumb} src={item.thumb} alt="" loading="lazy" />
                      ) : (
                        <span className={styles.thumb} />
                      )}
                      <span>
                        <span className={item.state === 'failed' ? styles.failed : undefined}>
                          {t(`uploads.state.${item.state}`)}
                        </span>
                        {item.error ? (
                          <span className={styles.uploaderMeta}> · {item.error}</span>
                        ) : null}
                        {item.created_at ? (
                          <span className={styles.uploaderMeta}>
                            {' '}
                            · {formatTime(item.created_at, locale, event.data?.timezone)}
                          </span>
                        ) : null}
                      </span>
                      {item.state === 'failed' ? (
                        <Button variant="quiet" small onClick={() => retry.mutate(item.id)}>
                          {t('common.retry')}
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </>
        ) : (
          <p className={styles.lead}>{uploads.isError ? t('common.error') : t('common.loading')}</p>
        )}
      </main>
    </>
  )
}
