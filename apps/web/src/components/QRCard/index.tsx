import { useT } from '~/i18n'
import styles from './QRCard.module.css'

interface Props {
  title: string
  hostName: string
  qrSrc: string
  url: string
}

export function QRCard({ title, hostName, qrSrc, url }: Props) {
  const t = useT()
  return (
    <section className={styles.card}>
      <div className={styles.eyebrow}>{t('landing.invites', { name: hostName })}</div>
      <h2 className={styles.title}>{title}</h2>
      <div className={styles.qr}>
        <img src={qrSrc} alt={t('share.scanHint')} width={320} height={320} />
      </div>
      <p className={styles.hint}>{t('share.scanHint')}</p>
      <p className={styles.url}>{url}</p>
    </section>
  )
}
