import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

const sizes: Record<Size, string> = {
  sm: 'h-7 px-2.5 text-caption',
  md: 'h-8 px-3 text-body',
  lg: 'h-9 px-4 text-body',
}

const variants: Record<Variant, string> = {
  primary: 'bg-ag-cinnabar text-ag-onCinnabar border border-transparent hover:bg-ag-cinnabarHover active:bg-ag-cinnabarPress',
  secondary: 'bg-transparent text-ag-ink2 border border-ag-line2 hover:bg-ag-bg4 hover:border-ag-line3 hover:text-ag-ink1',
  danger: 'bg-transparent text-ag-danger border border-ag-danger hover:bg-ag-bg4',
  ghost: 'bg-transparent text-ag-ink3 border border-transparent hover:bg-ag-bg4 hover:text-ag-ink1',
}

const disabledStyle =
  'disabled:bg-ag-disabledBg disabled:text-ag-disabledInk disabled:border-ag-disabledLine disabled:cursor-not-allowed'

export default function Button({
  variant = 'secondary', size = 'md', loading = false, icon,
  className = '', children, disabled, ...rest
}: Props) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`ag-focus-ring inline-flex items-center justify-center gap-1.5 shrink-0 rounded-btn font-medium transition-colors ${sizes[size]} ${variants[variant]} ${disabledStyle} ${className}`}
    >
      {loading ? <span className="ag-mono text-micro">...</span> : icon}
      {children}
    </button>
  )
}
