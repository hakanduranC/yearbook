import { createFileRoute } from '@tanstack/react-router'
import { ButtonLink } from '~/components/Button'
import { PageHeader } from '~/components/PageHeader'
import { useT } from '~/i18n'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/expired')({
  component: Expired,
})

function Expired() {
  const t = useT()
  return (
    <>
      <PageHeader title={t('login.title')} back="/" plain />
      <main className={`page page--narrow ${styles.main}`}>
        <h2 className={styles.title}>{t('expired.title')}</h2>
        <p className={styles.lead}>{t('expired.body')}</p>
        <div className={styles.actions}>
          <ButtonLink to="/login" search={{}}>
            {t('expired.again')}
          </ButtonLink>
        </div>
      </main>
    </>
  )
}
