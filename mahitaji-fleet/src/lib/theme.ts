/**
 * Design tokens, taken from the website's stylesheet (static/css/mahitaji.css) so the
 * app and the shop look like one brand.
 */
export const colors = {
  brand950: '#0a1931',
  brand900: '#112b4a',
  brand800: '#1a3d63',
  brand700: '#2b5580',
  brand600: '#3a6b96',
  brand500: '#4a7fa7',
  brand400: '#7ea6c8',
  brand200: '#b3cfe5',
  brand100: '#d6e5f2',
  brand50: '#f6fafd',

  amber600: '#b98a33',
  amber500: '#e0ad4f',
  amber100: '#fbf1dc',

  ink: '#0a1931',
  text: '#17304d',
  text2: '#3b5876',
  muted: '#5f7a98',
  line: '#dce7f1',
  line2: '#b3cfe5',
  bg: '#f6fafd',
  bg2: '#e8f1f8',
  surface: '#ffffff',

  danger: '#b4453d',
  danger100: '#f6e6e4',
  info: '#4a7fa7',
  info100: '#d6e5f2',
  warning: '#8a6a2c',
  warning100: '#f3eddf',
  success: '#33705a',
  success100: '#e4f0ea',
} as const;

export const fonts = {
  body: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  display: 'PlusJakartaSans_700Bold',
  displayHeavy: 'PlusJakartaSans_800ExtraBold',
} as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 24, pill: 999 } as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

export const shadow = { boxShadow: '0 4px 14px rgba(10, 25, 49, 0.08)' } as const;

/** Background / text pairs for status badges (order status tones, stock states). */
export const tones = {
  success: { bg: colors.success100, fg: colors.success },
  warning: { bg: colors.warning100, fg: colors.warning },
  danger: { bg: colors.danger100, fg: colors.danger },
  info: { bg: colors.info100, fg: colors.brand700 },
  muted: { bg: colors.bg2, fg: colors.muted },
} as const;

export type Tone = keyof typeof tones;
