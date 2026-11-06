import React from 'react';

export type BadgeTone = 'neutral' | 'primary' | 'success' | 'warning' | 'error';

interface StatusBadgeProps {
  tone?: BadgeTone;
  label: string;
}

const TONE_STYLES: Record<BadgeTone, string> = {
  neutral: 'bg-surface-subtle text-feedback-info border-border-default',
  primary: 'bg-blue-50 text-action-primary border-blue-200',
  success: 'bg-green-50 text-feedback-success border-green-200',
  warning: 'bg-amber-50 text-feedback-warning border-amber-200',
  error: 'bg-red-50 text-feedback-error border-red-200',
};

const TONE_INDICATOR: Record<BadgeTone, string> = {
  neutral: '●',
  primary: '◆',
  success: '✓',
  warning: '▲',
  error: '✕',
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  tone = 'neutral',
  label,
}) => {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_STYLES[tone]}`}
    >
      <span aria-hidden="true">{TONE_INDICATOR[tone]}</span>
      <span>{label}</span>
    </span>
  );
};
