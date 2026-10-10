import { type ErrorComponentProps, Link, useRouter } from '@tanstack/react-router'
import { Button, ButtonLink } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { useT } from '~/i18n'
import { isApiError } from '~/lib/api/client'

export function CatchBoundary({ error }: ErrorComponentProps) {
  const t = useT()
  const router = useRouter()
  if (isApiError(error) && error.status === 404) return <NotFound />
  return (
    <main className="page page--narrow">
      <EmptyState
        kind="not-found"
        title={t('error.title')}
        body={t('error.body')}
        action={
          <Button variant="secondary" onClick={() => router.invalidate()}>
            {t('error.reload')}
          </Button>
        }
      />
    </main>
  )
}

export function NotFound() {
  const t = useT()
  return (
    <main className="page page--narrow">
      <EmptyState
        kind="not-found"
        action={
          <ButtonLink to="/" variant="secondary">
            {t('nav.home')}
          </ButtonLink>
        }
      />
      <Link to="/" className="visually-hidden">
        {t('nav.home')}
      </Link>
    </main>
  )
}
