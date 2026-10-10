import { Link, type LinkProps } from '@tanstack/react-router'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import styles from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'quiet' | 'danger' | 'like'

interface Common {
  variant?: ButtonVariant
  block?: boolean
  small?: boolean
  busy?: boolean
  className?: string
  children?: ReactNode
}

export type ButtonProps = Common &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'children'>

export function buttonClass({
  variant = 'primary',
  block,
  small,
  busy,
  className,
}: Common): string {
  return [
    styles.button,
    variant !== 'primary' ? styles[variant] : null,
    block ? styles.block : null,
    small ? styles.small : null,
    busy ? styles.busy : null,
    className,
  ]
    .filter(Boolean)
    .join(' ')
}

export function Button({
  variant,
  block,
  small,
  busy,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClass({ variant, block, small, busy, className })}
      aria-busy={busy || undefined}
      {...rest}
    >
      {children}
    </button>
  )
}

export type ButtonLinkProps = Common &
  Omit<LinkProps, 'className' | 'children'> & { 'aria-disabled'?: boolean }

export function ButtonLink({
  variant,
  block,
  small,
  busy,
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link className={buttonClass({ variant, block, small, busy, className })} {...rest}>
      {children}
    </Link>
  )
}

export function ButtonAnchor({
  variant,
  block,
  small,
  busy,
  className,
  children,
  ...rest
}: Common & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'className' | 'children'>) {
  return (
    <a className={buttonClass({ variant, block, small, busy, className })} {...rest}>
      {children}
    </a>
  )
}
