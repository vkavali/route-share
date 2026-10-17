import React, {createContext, useContext, useState} from 'react';
import {Platform, Pressable, StyleSheet, Text as NativeText, View} from 'react-native';
import {useFonts} from 'expo-font';
import {T} from './translation';
import {SeatPalLoader} from './SeatPalLoader';
import {revealNativeFrame} from './startupSplash';
import {SeatPalTheme} from './SeatPalTheme';

const fontAssets = {
  Manrope400: require('../assets/fonts/Manrope-400.ttf'),
  Manrope500: require('../assets/fonts/Manrope-500.ttf'),
  Manrope600: require('../assets/fonts/Manrope-600.ttf'),
  Manrope700: require('../assets/fonts/Manrope-700.ttf'),
  AnekTelugu400: require('../assets/fonts/AnekTelugu-400.ttf'),
  AnekTelugu500: require('../assets/fonts/AnekTelugu-500.ttf'),
  AnekTelugu600: require('../assets/fonts/AnekTelugu-600.ttf'),
  AnekTelugu700: require('../assets/fonts/AnekTelugu-700.ttf'),
};

const LanguageContext = createContext('en');

export function NativeTypographyProvider({lang, children, startupPending=false}: {lang: string; children: React.ReactNode; startupPending?: boolean}) {
  const [attempt, setAttempt] = useState(0);
  return <FontLoader key={attempt} lang={lang} startupPending={startupPending} onRetry={() => setAttempt(value => value + 1)}>{children}</FontLoader>;
}

function FontLoader({lang, children, onRetry, startupPending}: {lang: string; children: React.ReactNode; onRetry: () => void; startupPending: boolean}) {
  const [loaded, error] = useFonts(fontAssets);
  if (error) {
    return <View onLayout={revealNativeFrame} style={styles.failure}>
      <NativeText style={styles.failureText}>{T(lang, 'fontLoadError')}</NativeText>
      <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
        <NativeText style={styles.retryText}>{T(lang, 'retry')}</NativeText>
      </Pressable>
    </View>;
  }
  if (!loaded || startupPending) {
    return <View onLayout={revealNativeFrame} style={styles.loading}><SeatPalLoader variant="startup" label={T(lang,'loading')}/></View>;
  }
  return <LanguageContext.Provider value={lang}><View onLayout={revealNativeFrame} style={{flex:1}}>{children}</View></LanguageContext.Provider>;
}

export function AppText({style, lang: scriptLang, ...props}: React.ComponentProps<typeof NativeText> & {lang?: string}) {
  const contextLang = useContext(LanguageContext);
  const lang = scriptLang || contextLang;
  const textStyle = StyleSheet.flatten(style) || {};
  const bodyAlias = /^(?:Manrope|AnekTelugu)(400|500|600|700)$/.exec(textStyle.fontFamily || '');
  const customFont = Boolean(textStyle.fontFamily && !bodyAlias && !['System', 'sans-serif'].includes(textStyle.fontFamily));
  // Leave explicit icon, monospace, and other custom families exactly as requested.
  if (customFont) return <NativeText {...props} style={style} />;
  const requested = String(textStyle.fontWeight || bodyAlias?.[1] || '400');
  const weight = requested === 'normal' ? '400' : requested === 'bold' ? '700' : requested;
  const teluguWeight = ['500', '600', '700'].includes(weight)
    ? weight : ['800', '900'].includes(weight) ? '700' : '400';
  const family = lang === 'te' ? `AnekTelugu${teluguWeight}` : Platform.OS === 'ios' ? 'System' : 'sans-serif';
  const size = Number(textStyle.fontSize || SeatPalTheme.type.body);
  const lineHeight = lang === 'te'
    ? Math.max(Number(textStyle.lineHeight || 0), Math.ceil(size * 1.5))
    : textStyle.lineHeight || Math.ceil(size * 1.4);

  return <NativeText {...props} style={[
    {color: SeatPalTheme.colors.text, fontSize: SeatPalTheme.type.body},
    style,
    {fontFamily: family, fontWeight: lang === 'te' ? 'normal' : weight as '400' | '500' | '600' | '700' | '800' | '900',
      lineHeight, letterSpacing: lang === 'te' ? 0 : textStyle.letterSpacing},
  ]} />;
}

const styles = StyleSheet.create({
  loading: {flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: SeatPalTheme.colors.page},
  failure: {flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24, backgroundColor: SeatPalTheme.colors.page},
  failureText: {maxWidth: 330, textAlign: 'center', color: SeatPalTheme.colors.text, fontSize: 16, lineHeight: 25},
  retry: {minHeight: SeatPalTheme.target, justifyContent: 'center', paddingHorizontal: 20, borderRadius: SeatPalTheme.radius.control, backgroundColor: SeatPalTheme.colors.primary},
  retryText: {color: SeatPalTheme.colors.onPrimary, fontSize: 15, fontWeight: '700'},
});
