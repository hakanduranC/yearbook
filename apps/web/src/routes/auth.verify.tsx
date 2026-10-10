import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import * as v from 'valibot'
import { useT } from '~/i18n'
import { safeNext } from '~/lib/guards'
import { keys } from '~/lib/queries/keys'
import { verifyMagicLink } from '~/lib/queries/me'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/auth/verify')({
  validateSearch: v.object({ token: v.optional(v.string()), next: v.optional(v.string()) }),
  component: Verify,
})

function Verify() {
  const t = useT()
  const { token, next } = Route.useSearch()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const started = useRef(false)

  // The email links here with a GET so scanners cannot burn the token; the browser POSTs it once.
  useEffect(() => {
    if (started.current) return
    started.current = true
    if (!token) {
      navigate({ to: '/expired', replace: true })
      return
    }
    verifyMagicLink(token)
      .then((res) => {
        queryClient.setQueryData(keys.me(), res.me)
        queryClient.invalidateQueries({ queryKey: keys.events() })
        navigate({ href: safeNext(res.next || next), replace: true })
      })
      .catch(() => navigate({ to: '/expired', replace: true }))
  }, [token, next, navigate, queryClient])

  return (
    <main className={`page page--narrow ${styles.main}`}>
      <p className={styles.lead} role="status">
        {t('verify.working')}
      </p>
    </main>
  )
}
