import { type InputHTMLAttributes, type ReactNode, useId } from 'react'
import { useT } from '~/i18n'
import styles from './Field.module.css'

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  optional?: boolean
}

export function Field({ label, hint, error, optional, className, ...input }: FieldProps) {
  const id = useId()
  const t = useT()
  return (
    <div className={[styles.field, className].filter(Boolean).join(' ')}>
      <label className={styles.label} htmlFor={id}>
        {label}
        {optional ? <span className={styles.optional}>({t('common.optional')})</span> : null}
      </label>
      <input
        id={id}
        className={styles.input}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? `${id}-hint` : undefined}
        {...input}
      />
      {error ? (
        <span id={`${id}-hint`} className={styles.error} role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      ) : null}
    </div>
  )
}

interface SwitchProps {
  label: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}

export function SwitchRow({ label, checked, onChange, disabled }: SwitchProps) {
  const id = useId()
  return (
    <div className={styles.row}>
      <span id={id} className={styles.label}>
        {label}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={id}
        className={styles.switch}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      />
    </div>
  )
}
