import React from 'react';
import {Pressable, ScrollView, StyleSheet, View} from 'react-native';
import {AppText} from './NativeTypography';
import {SeatPalTheme} from './SeatPalTheme';

type Language = 'en' | 'te' | 'hi';
const copy: Record<Language, Record<string, string>> = {
  en: {
    unlockTitle: 'Unlock SeatPal',
    unlockHelp: 'Use Face ID to unlock the saved sign-in on this iPhone.',
    unlock: 'Unlock with Face ID',
    useLogin: 'Use normal sign-in',
    settingTitle: 'Face ID',
    settingHelp: 'Protects your saved sign-in on this iPhone. Your face stays on this device.',
    sessionLimit: 'Face ID works while your saved session is valid. When it expires, sign in normally.',
    enable: 'Enable Face ID',
    disable: 'Turn off Face ID',
    setup: 'Set up Face ID in iPhone Settings to enable this option.',
    unlocking: 'Unlocking…',
    saving: 'Saving…',
    prompt: 'Unlock your saved SeatPal sign-in',
    notUnlocked: 'Face ID did not unlock SeatPal. Try again or use normal sign-in.',
    missing: 'Your saved sign-in is no longer available. Sign in normally to continue.',
    changeFailed: 'Could not change Face ID. Try again.',
    storageFailed: 'Could not clear the saved sign-in. Keep SeatPal closed and retry.',
    wrongAccount: 'The saved account could not be verified. Sign in again.',
  },
  te: {
    unlockTitle: 'SeatPalను అన్‌లాక్ చేయండి',
    unlockHelp: 'ఈ iPhoneలో సేవ్ చేసిన సైన్-ఇన్‌ను అన్‌లాక్ చేయడానికి Face IDని ఉపయోగించండి.',
    unlock: 'Face IDతో అన్‌లాక్ చేయండి',
    useLogin: 'సాధారణ సైన్-ఇన్ ఉపయోగించండి',
    settingTitle: 'Face ID',
    settingHelp: 'ఈ iPhoneలోని సేవ్ చేసిన సైన్-ఇన్‌ను రక్షిస్తుంది. మీ ముఖం ఈ పరికరంలోనే ఉంటుంది.',
    sessionLimit: 'మీ సేవ్ చేసిన సెషన్ చెల్లుబాటులో ఉన్నంతవరకే Face ID పని చేస్తుంది. గడువు ముగిస్తే సాధారణంగా సైన్-ఇన్ చేయండి.',
    enable: 'Face IDని ఆన్ చేయండి',
    disable: 'Face IDని ఆఫ్ చేయండి',
    setup: 'ఈ ఎంపికను ఆన్ చేయడానికి iPhone సెట్టింగ్‌లలో Face IDని సెటప్ చేయండి.',
    unlocking: 'అన్‌లాక్ చేస్తోంది…',
    saving: 'సేవ్ చేస్తోంది…',
    prompt: 'సేవ్ చేసిన SeatPal సైన్-ఇన్‌ను అన్‌లాక్ చేయండి',
    notUnlocked: 'Face IDతో SeatPal అన్‌లాక్ కాలేదు. మళ్లీ ప్రయత్నించండి లేదా సాధారణ సైన్-ఇన్ ఉపయోగించండి.',
    missing: 'సేవ్ చేసిన సైన్-ఇన్ ఇప్పుడు అందుబాటులో లేదు. కొనసాగించడానికి సాధారణంగా సైన్-ఇన్ చేయండి.',
    changeFailed: 'Face IDని మార్చలేకపోయాం. మళ్లీ ప్రయత్నించండి.',
    storageFailed: 'సేవ్ చేసిన సైన్-ఇన్‌ను తొలగించలేకపోయాం. SeatPalను మూసి మళ్లీ ప్రయత్నించండి.',
    wrongAccount: 'సేవ్ చేసిన అకౌంట్‌ను ధృవీకరించలేకపోయాం. మళ్లీ సైన్-ఇన్ చేయండి.',
  },
  hi: {
    unlockTitle: 'SeatPal अनलॉक करें',
    unlockHelp: 'इस iPhone पर सेव किए गए साइन-इन को अनलॉक करने के लिए Face ID का उपयोग करें।',
    unlock: 'Face ID से अनलॉक करें',
    useLogin: 'सामान्य साइन-इन करें',
    settingTitle: 'Face ID',
    settingHelp: 'इस iPhone पर सेव किए गए साइन-इन को सुरक्षित रखता है। आपका चेहरा इसी डिवाइस पर रहता है।',
    sessionLimit: 'Face ID तभी काम करता है जब आपका सेव किया गया सेशन मान्य हो। इसकी अवधि पूरी होने पर सामान्य तरीके से साइन-इन करें।',
    enable: 'Face ID चालू करें',
    disable: 'Face ID बंद करें',
    setup: 'इस विकल्प को चालू करने के लिए iPhone Settings में Face ID सेट अप करें।',
    unlocking: 'अनलॉक हो रहा है…',
    saving: 'सेव हो रहा है…',
    prompt: 'अपना सेव किया गया SeatPal साइन-इन अनलॉक करें',
    notUnlocked: 'Face ID से SeatPal अनलॉक नहीं हुआ। फिर कोशिश करें या सामान्य साइन-इन करें।',
    missing: 'आपका सेव किया गया साइन-इन अब उपलब्ध नहीं है। जारी रखने के लिए सामान्य तरीके से साइन-इन करें।',
    changeFailed: 'Face ID बदल नहीं पाए। फिर कोशिश करें।',
    storageFailed: 'सेव किया गया साइन-इन मिटा नहीं पाए। SeatPal बंद रखें और फिर कोशिश करें।',
    wrongAccount: 'सेव किए गए अकाउंट की पुष्टि नहीं हो सकी। फिर साइन-इन करें।',
  },
};

function text(lang: string, key: string) {
  const dictionary = copy[lang as Language] || copy.en;
  return dictionary[key] || copy.en[key] || key;
}

export function faceIdLabels(lang: string) {
  const dictionary = copy[lang as Language] || copy.en;
  return {
    prompt: dictionary.prompt,
    notUnlocked: dictionary.notUnlocked,
    missing: dictionary.missing,
    changeFailed: dictionary.changeFailed,
    storageFailed: dictionary.storageFailed,
    wrongAccount: dictionary.wrongAccount,
    sessionLimit: dictionary.sessionLimit,
  };
}

type FaceIdUnlockScreenProps = {
  lang: string;
  busy: boolean;
  message: string;
  onUnlock: () => void;
  onUseLogin: () => void;
};

export function FaceIdUnlockScreen({lang, busy, message, onUnlock, onUseLogin}: FaceIdUnlockScreenProps) {
  const t = (key: string) => text(lang, key);
  return <ScrollView contentContainerStyle={styles.unlockPage} keyboardShouldPersistTaps="handled"><View style={styles.card}>
    <AppText accessibilityRole="header" style={styles.title}>{t('unlockTitle')}</AppText>
    <AppText style={styles.help}>{t('unlockHelp')}</AppText>
    {message ? <AppText accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.message}>{message}</AppText> : null}
    {busy ? <AppText accessibilityLiveRegion="polite" style={styles.busy}>{t('unlocking')}</AppText> : null}
    <Pressable testID="face-id-unlock" accessibilityRole="button" accessibilityLabel={t('unlock')} accessibilityState={{disabled: busy, busy}} disabled={busy} onPress={onUnlock} style={[styles.button, busy && styles.disabled]}>
      <AppText style={styles.primaryText}>{t('unlock')}</AppText>
    </Pressable>
    <Pressable testID="face-id-use-login" accessibilityRole="button" accessibilityLabel={t('useLogin')} accessibilityState={{disabled: busy, busy}} disabled={busy} onPress={onUseLogin} style={[styles.button, styles.secondaryButton, busy && styles.disabled]}>
      <AppText style={styles.secondaryText}>{t('useLogin')}</AppText>
    </Pressable>
  </View></ScrollView>;
}

type FaceIdSettingProps = {
  lang: string;
  enabled: boolean;
  available: boolean;
  busy: boolean;
  message: string;
  onToggle: () => void;
};

export function FaceIdSetting({lang, enabled, available, busy, message, onToggle}: FaceIdSettingProps) {
  const t = (key: string) => text(lang, key);
  const label = t(enabled ? 'disable' : 'enable');
  const disabled = busy || (!available && !enabled);
  return <View style={styles.card}>
    <AppText accessibilityRole="header" style={styles.settingTitle}>{t('settingTitle')}</AppText>
    <AppText style={styles.help}>{t('settingHelp')} {t('sessionLimit')}</AppText>
    {!available && !enabled ? <AppText style={styles.setup}>{t('setup')}</AppText> : null}
    {message ? <AppText accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.message}>{message}</AppText> : null}
    {busy ? <AppText accessibilityLiveRegion="polite" style={styles.busy}>{t('saving')}</AppText> : null}
    <Pressable testID="face-id-toggle" accessibilityRole="button" accessibilityLabel={label} accessibilityState={{disabled, checked: enabled, busy}} disabled={disabled} onPress={onToggle} style={[styles.button, enabled && styles.secondaryButton, styles.toggle, disabled && styles.disabled]}>
      <AppText style={enabled ? styles.secondaryText : styles.primaryText}>{label}</AppText>
    </Pressable>
  </View>;
}

const styles = StyleSheet.create({
  card: {backgroundColor: SeatPalTheme.colors.surface, padding: SeatPalTheme.spacing.lg, borderRadius: SeatPalTheme.radius.card, borderWidth: 1, borderColor: SeatPalTheme.colors.border, gap: SeatPalTheme.spacing.md},
  unlockPage: {flexGrow: 1, justifyContent: 'center', padding: SeatPalTheme.spacing.md},
  title: {fontSize: 28, fontWeight: '700', color: SeatPalTheme.colors.primary},
  settingTitle: {fontSize: 20, fontWeight: '700', color: SeatPalTheme.colors.primary},
  help: {fontSize: 15, lineHeight: 22, color: SeatPalTheme.colors.secondary},
  setup: {fontSize: 14, lineHeight: 21, color: SeatPalTheme.colors.secondary, backgroundColor: SeatPalTheme.colors.subtle, padding: SeatPalTheme.spacing.md, borderRadius: SeatPalTheme.radius.control},
  message: {fontSize: 14, lineHeight: 21, color: SeatPalTheme.colors.danger},
  busy: {fontSize: 14, fontWeight: '600', color: SeatPalTheme.colors.secondary},
  button: {minHeight: SeatPalTheme.target, borderRadius: SeatPalTheme.radius.control, backgroundColor: SeatPalTheme.colors.primary, alignItems: 'center', justifyContent: 'center', paddingHorizontal: SeatPalTheme.spacing.md, paddingVertical: SeatPalTheme.spacing.sm},
  secondaryButton: {backgroundColor: SeatPalTheme.colors.selected},
  toggle: {alignSelf: 'flex-start', minWidth: 170},
  primaryText: {fontSize: 16, fontWeight: '700', color: SeatPalTheme.colors.onPrimary, textAlign: 'center'},
  secondaryText: {fontSize: 16, fontWeight: '700', color: SeatPalTheme.colors.primary, textAlign: 'center'},
  disabled: {opacity: 0.45},
});
