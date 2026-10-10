import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Button } from '~/components/Button'
import { PageHeader } from '~/components/PageHeader'
import { QRCard } from '~/components/QRCard'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import { publicOrigin } from '~/lib/env'
import { requireHost } from '~/lib/guards'
import { eventQuery } from '~/lib/queries/event'
import { eventUrl, qrUrl } from '~/lib/queries/share'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/e/$slug/share')({
  beforeLoad: async ({ context: { queryClient }, params, location }) => {
    await requireHost(queryClient, params.slug, location.href)
  },
  loader: () => ({ origin: publicOrigin() }),
  component: Share,
})

function Share() {
  const t = useT()
  const toast = useToast()
  const { slug } = Route.useParams()
  const { origin } = Route.useLoaderData()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const url = eventUrl(origin, slug)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      toast(t('common.copied'))
    } catch {
      toast(t('common.error'))
    }
  }

  const share = async () => {
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title: event.title, url })
        return
      } catch {
        // fall through to copy
      }
    }
    copy()
  }

  return (
    <>
      <div className="no-print">
        <PageHeader title={t('share.title')} back="/e/$slug" backParams={{ slug }} />
      </div>
      <main className={`page page--narrow ${styles.main}`}>
        <p className={`${styles.lead} no-print`}>{t('share.lead')}</p>
        <QRCard
          title={event.title}
          hostName={event.host.display_name}
          qrSrc={qrUrl(slug)}
          url={url}
        />
        <div className={`${styles.linkRow} no-print`}>
          <span className={styles.linkBox}>{url}</span>
          <Button variant="secondary" onClick={copy}>
            {t('common.copy')}
          </Button>
        </div>
        <div className={`${styles.actions} no-print`}>
          <Button onClick={share}>{t('common.share')}</Button>
          <Button variant="secondary" onClick={() => window.print()}>
            {t('share.print')}
          </Button>
        </div>
      </main>
    </>
  )
}
